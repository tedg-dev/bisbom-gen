// Package indexer — graph.go implements the segmented adjacency list
// pattern for storing SPDX dependency graphs in DynamoDB.
//
// Each package in the dependency tree is stored as its own DynamoDB
// item keyed by (ArtifactSHA256, depth#N#PURL). This avoids the
// 400 KB item size limit and enables efficient depth-based range
// queries.
package indexer

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"strings"

	"github.com/aws/aws-sdk-go-v2/feature/dynamodb/attributevalue"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// GraphNode is a single DynamoDB item in the SpdxDependencyGraph table.
type GraphNode struct {
	ArtifactSHA256 string   `dynamodbav:"ArtifactSHA256"`
	SK             string   `dynamodbav:"SK"`
	Purl           string   `dynamodbav:"purl"`
	Name           string   `dynamodbav:"name"`
	Version        string   `dynamodbav:"version"`
	Supplier       string   `dynamodbav:"supplier,omitempty"`
	Scope          string   `dynamodbav:"scope,omitempty"`
	Depth          int      `dynamodbav:"depth"`
	Parent         string   `dynamodbav:"parent,omitempty"`
	Children       []string `dynamodbav:"children,omitempty"`
}

// spdxDoc is the subset of an SPDX 2.3 JSON document we need.
type spdxDoc struct {
	Packages      []spdxPackage      `json:"packages"`
	Relationships []spdxRelationship `json:"relationships"`
}

// spdxPackage is a single package from the SPDX packages array.
type spdxPackage struct {
	SPDXID       string        `json:"SPDXID"`
	Name         string        `json:"name"`
	VersionInfo  string        `json:"versionInfo"`
	Supplier     string        `json:"supplier,omitempty"`
	Comment      string        `json:"comment,omitempty"`
	ExternalRefs []externalRef `json:"externalRefs,omitempty"`
}

// externalRef is a package external reference (PURL, CPE, etc.).
type externalRef struct {
	Category string `json:"referenceCategory"`
	Type     string `json:"referenceType"`
	Locator  string `json:"referenceLocator"`
}

// spdxRelationship is a single SPDX relationship.
type spdxRelationship struct {
	ElementID    string `json:"spdxElementId"`
	RelatedID    string `json:"relatedSpdxElement"`
	RelationType string `json:"relationshipType"`
}

// IndexGraph parses the build SPDX JSON from S3 and writes the
// dependency graph to the SpdxDependencyGraph table.
func (ix *Indexer) IndexGraph(
	ctx context.Context,
	artifactSHA256 string,
	buildSpdxKey string,
	graphTable string,
) error {
	doc, err := ix.loadSpdxDoc(ctx, buildSpdxKey)
	if err != nil {
		return fmt.Errorf("load spdx doc: %w", err)
	}

	nodes := buildGraph(artifactSHA256, doc)
	if len(nodes) == 0 {
		log.Printf("[GRAPH] No dependency nodes found in %s", buildSpdxKey)
		return nil
	}

	written := 0
	for _, node := range nodes {
		if ix.DryRun {
			log.Printf("[DRY-RUN] Would write graph node: %s depth=%d children=%d",
				node.Purl, node.Depth, len(node.Children))
		} else {
			if err := ix.putGraphNode(ctx, graphTable, node); err != nil {
				return fmt.Errorf("put graph node %s: %w", node.Purl, err)
			}
		}
		written++
	}

	log.Printf("[GRAPH] Wrote %d dependency nodes for %s", written, artifactSHA256[:12])
	return nil
}

// loadSpdxDoc downloads and parses an SPDX JSON document from S3.
func (ix *Indexer) loadSpdxDoc(ctx context.Context, s3Key string) (*spdxDoc, error) {
	out, err := ix.s3Client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: &ix.bucket,
		Key:    &s3Key,
	})
	if err != nil {
		return nil, fmt.Errorf("get %s: %w", s3Key, err)
	}
	defer out.Body.Close()

	data, err := io.ReadAll(out.Body)
	if err != nil {
		return nil, fmt.Errorf("read %s: %w", s3Key, err)
	}

	var doc spdxDoc
	if err := json.Unmarshal(data, &doc); err != nil {
		return nil, fmt.Errorf("parse %s: %w", s3Key, err)
	}
	return &doc, nil
}

// buildGraph constructs GraphNode items from SPDX packages and
// DEPENDS_ON relationships using BFS to compute depth.
func buildGraph(artifactSHA256 string, doc *spdxDoc) []GraphNode {
	// Index packages by SPDXID
	pkgByID := make(map[string]*spdxPackage, len(doc.Packages))
	for i := range doc.Packages {
		pkgByID[doc.Packages[i].SPDXID] = &doc.Packages[i]
	}

	// Build adjacency list from DEPENDS_ON relationships:
	// parent SPDXID → list of child SPDXIDs
	children := make(map[string][]string)
	parentOf := make(map[string]string)
	for _, rel := range doc.Relationships {
		if rel.RelationType != "DEPENDS_ON" {
			continue
		}
		children[rel.ElementID] = append(children[rel.ElementID], rel.RelatedID)
		// Record parent (first parent wins for display; a node
		// may appear under multiple parents in the resolved tree
		// but Maven resolves one version per artifact).
		if _, exists := parentOf[rel.RelatedID]; !exists {
			parentOf[rel.RelatedID] = rel.ElementID
		}
	}

	// Find root package (the one DESCRIBES targets)
	var rootID string
	for _, rel := range doc.Relationships {
		if rel.RelationType == "DESCRIBES" {
			rootID = rel.RelatedID
			break
		}
	}
	if rootID == "" {
		return nil
	}

	// BFS from root to compute depth
	type bfsEntry struct {
		spdxID string
		depth  int
	}
	queue := []bfsEntry{{spdxID: rootID, depth: 0}}
	visited := make(map[string]int) // spdxID → depth
	visited[rootID] = 0
	// Preserve BFS order for deterministic output
	var ordered []bfsEntry

	for len(queue) > 0 {
		entry := queue[0]
		queue = queue[1:]
		ordered = append(ordered, entry)

		for _, childID := range children[entry.spdxID] {
			if _, seen := visited[childID]; !seen {
				visited[childID] = entry.depth + 1
				queue = append(queue, bfsEntry{
					spdxID: childID,
					depth:  entry.depth + 1,
				})
			}
		}
	}

	// Build GraphNode items
	var nodes []GraphNode
	for _, entry := range ordered {
		pkg := pkgByID[entry.spdxID]
		if pkg == nil {
			continue
		}

		purl := extractPurl(pkg)
		if purl == "" {
			// Fall back to a synthetic identifier
			purl = fmt.Sprintf("pkg:spdx/%s@%s", pkg.Name, pkg.VersionInfo)
		}

		node := GraphNode{
			ArtifactSHA256: artifactSHA256,
			SK:             fmt.Sprintf("depth#%d#%s", entry.depth, purl),
			Purl:           purl,
			Name:           pkg.Name,
			Version:        pkg.VersionInfo,
			Supplier:       cleanSupplier(pkg.Supplier),
			Scope:          extractScope(pkg.Comment),
			Depth:          entry.depth,
		}

		// Set parent PURL
		if parentID, ok := parentOf[entry.spdxID]; ok {
			if parentPkg := pkgByID[parentID]; parentPkg != nil {
				node.Parent = extractPurl(parentPkg)
			}
		}

		// Set children PURLs
		for _, childID := range children[entry.spdxID] {
			if childPkg := pkgByID[childID]; childPkg != nil {
				childPurl := extractPurl(childPkg)
				if childPurl != "" {
					node.Children = append(node.Children, childPurl)
				}
			}
		}

		nodes = append(nodes, node)
	}

	return nodes
}

// putGraphNode writes a single GraphNode to the dependency graph table.
func (ix *Indexer) putGraphNode(ctx context.Context, table string, node GraphNode) error {
	item, err := attributevalue.MarshalMap(node)
	if err != nil {
		return fmt.Errorf("marshal node: %w", err)
	}

	_, err = ix.dynamoClient.PutItem(ctx, &dynamodb.PutItemInput{
		TableName: &table,
		Item:      item,
	})
	return err
}

// extractPurl returns the PURL from a package's external references.
func extractPurl(pkg *spdxPackage) string {
	for _, ref := range pkg.ExternalRefs {
		if ref.Type == "purl" {
			return ref.Locator
		}
	}
	return ""
}

// cleanSupplier strips the "Organization: " prefix from SPDX supplier.
func cleanSupplier(supplier string) string {
	return strings.TrimPrefix(supplier, "Organization: ")
}

// extractScope parses the Maven scope from the SPDX comment field.
// e.g. "Maven scope: compile. Direct dependency" → "compile"
func extractScope(comment string) string {
	const prefix = "Maven scope: "
	idx := strings.Index(comment, prefix)
	if idx < 0 {
		return ""
	}
	rest := comment[idx+len(prefix):]
	if dot := strings.Index(rest, "."); dot > 0 {
		return rest[:dot]
	}
	return rest
}
