// Package treegen queries the SpdxDependencyGraph DynamoDB table and
// reconstructs a nested dependency tree in JSON format.
package treegen

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/feature/dynamodb/attributevalue"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	dbtypes "github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// Generator reads the dependency graph from DynamoDB, builds a nested
// tree, and uploads the result to S3.
type Generator struct {
	dynamoClient *dynamodb.Client
	s3Client     *s3.Client
}

// New creates a Generator from the given AWS config.
func New(awsCfg aws.Config) *Generator {
	return &Generator{
		dynamoClient: dynamodb.NewFromConfig(awsCfg),
		s3Client:     s3.NewFromConfig(awsCfg),
	}
}

// Request describes a single sbom-tree generation job.
type Request struct {
	ArtifactSHA256 string `json:"artifactSHA256"`
	ArtifactName   string `json:"artifactName"`
	JobPrefix      string `json:"jobPrefix"`
	Bucket         string `json:"bucket"`
	GraphTable     string `json:"graphTable"`
	IndexTable     string `json:"indexTable"`
}

// TreeOutput is the top-level JSON written to S3.
type TreeOutput struct {
	ArtifactSHA256 string    `json:"artifactSHA256"`
	ArtifactName   string    `json:"artifactName"`
	GeneratedAt    time.Time `json:"generatedAt"`
	Root           *TreeNode `json:"root,omitempty"`
	Stats          TreeStats `json:"stats"`
}

// TreeNode is a single package in the nested tree.
type TreeNode struct {
	Purl       string      `json:"purl"`
	Name       string      `json:"name"`
	Version    string      `json:"version"`
	Supplier   string      `json:"supplier,omitempty"`
	Scope      string      `json:"scope,omitempty"`
	Depth      int         `json:"depth"`
	Dependency []*TreeNode `json:"dependency,omitempty"`
}

// TreeStats summarizes the dependency tree.
type TreeStats struct {
	TotalPackages      int `json:"totalPackages"`
	MaxDepth           int `json:"maxDepth"`
	DirectDependencies int `json:"directDependencies"`
}

// graphItem mirrors the DynamoDB GraphNode schema.
type graphItem struct {
	ArtifactSHA256 string   `dynamodbav:"ArtifactSHA256"`
	SK             string   `dynamodbav:"SK"`
	Purl           string   `dynamodbav:"purl"`
	Name           string   `dynamodbav:"name"`
	Version        string   `dynamodbav:"version"`
	Supplier       string   `dynamodbav:"supplier"`
	Scope          string   `dynamodbav:"scope"`
	Depth          int      `dynamodbav:"depth"`
	Parent         string   `dynamodbav:"parent"`
	Children       []string `dynamodbav:"children"`
}

// Generate queries DynamoDB for the full dependency graph, builds a
// nested tree, and uploads it to S3.
func (g *Generator) Generate(ctx context.Context, req Request) error {
	items, err := g.queryAllNodes(ctx, req.GraphTable, req.ArtifactSHA256)
	if err != nil {
		return fmt.Errorf("query graph nodes: %w", err)
	}

	if len(items) == 0 {
		log.Printf("[TREE] No graph nodes found for %s", req.ArtifactSHA256[:12])
		return nil
	}

	tree := buildTree(items)
	stats := computeStats(items)

	output := TreeOutput{
		ArtifactSHA256: req.ArtifactSHA256,
		ArtifactName:   req.ArtifactName,
		GeneratedAt:    time.Now().UTC(),
		Root:           tree,
		Stats:          stats,
	}

	data, err := json.MarshalIndent(output, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal tree: %w", err)
	}

	s3Key := fmt.Sprintf("%s/spdx/%s-sbom-tree.json", req.JobPrefix, req.ArtifactName)
	if err := g.uploadToS3(ctx, req.Bucket, s3Key, data); err != nil {
		return fmt.Errorf("upload tree: %w", err)
	}

	s3URI := fmt.Sprintf("s3://%s/%s", req.Bucket, s3Key)
	log.Printf("[TREE] Uploaded %s (%d packages, max depth %d)",
		s3Key, stats.TotalPackages, stats.MaxDepth)

	// Update the SpdxIndexTable record with the tree S3 location
	if req.IndexTable != "" {
		if err := g.updateIndexRecord(ctx, req.IndexTable, req.ArtifactSHA256, s3URI); err != nil {
			log.Printf("[TREE] Warning: failed to update index record: %v", err)
		}
	}

	return nil
}

// updateIndexRecord sets the SbomTreeS3 attribute on the existing
// SpdxIndexTable record for this artifact.
func (g *Generator) updateIndexRecord(
	ctx context.Context,
	table, artifactSHA256, s3URI string,
) error {
	_, err := g.dynamoClient.UpdateItem(ctx, &dynamodb.UpdateItemInput{
		TableName: &table,
		Key: map[string]dbtypes.AttributeValue{
			"ArtifactSHA256": &dbtypes.AttributeValueMemberS{Value: artifactSHA256},
		},
		UpdateExpression: aws.String("SET SbomTreeS3 = :uri"),
		ExpressionAttributeValues: map[string]dbtypes.AttributeValue{
			":uri": &dbtypes.AttributeValueMemberS{Value: s3URI},
		},
	})
	if err != nil {
		return fmt.Errorf("update item: %w", err)
	}
	log.Printf("[TREE] Updated index record %s with SbomTreeS3", artifactSHA256[:12])
	return nil
}

// queryAllNodes fetches every item for the given ArtifactSHA256
// partition key, paginating as needed.
func (g *Generator) queryAllNodes(
	ctx context.Context,
	table string,
	artifactSHA256 string,
) ([]graphItem, error) {
	var items []graphItem

	paginator := dynamodb.NewQueryPaginator(g.dynamoClient, &dynamodb.QueryInput{
		TableName:              &table,
		KeyConditionExpression: aws.String("ArtifactSHA256 = :sha"),
		ExpressionAttributeValues: map[string]dbtypes.AttributeValue{
			":sha": &dbtypes.AttributeValueMemberS{Value: artifactSHA256},
		},
	})

	for paginator.HasMorePages() {
		page, err := paginator.NextPage(ctx)
		if err != nil {
			return nil, fmt.Errorf("query page: %w", err)
		}

		for _, rawItem := range page.Items {
			var item graphItem
			if err := attributevalue.UnmarshalMap(rawItem, &item); err != nil {
				return nil, fmt.Errorf("unmarshal item: %w", err)
			}
			items = append(items, item)
		}
	}

	return items, nil
}

// buildTree reconstructs a nested tree from flat graph items.
func buildTree(items []graphItem) *TreeNode {
	// Build nodes indexed by PURL
	nodeByPurl := make(map[string]*TreeNode, len(items))
	for _, item := range items {
		nodeByPurl[item.Purl] = &TreeNode{
			Purl:     item.Purl,
			Name:     item.Name,
			Version:  item.Version,
			Supplier: item.Supplier,
			Scope:    item.Scope,
			Depth:    item.Depth,
		}
	}

	// Wire up dependency relationships using the children list
	var root *TreeNode
	for _, item := range items {
		node := nodeByPurl[item.Purl]
		if item.Depth == 0 {
			root = node
		}
		for _, childPurl := range item.Children {
			if childNode, ok := nodeByPurl[childPurl]; ok {
				node.Dependency = append(node.Dependency, childNode)
			}
		}
	}

	return root
}

// computeStats calculates summary statistics for the tree.
func computeStats(items []graphItem) TreeStats {
	stats := TreeStats{
		TotalPackages: len(items),
	}
	for _, item := range items {
		if item.Depth > stats.MaxDepth {
			stats.MaxDepth = item.Depth
		}
		if item.Depth == 1 {
			stats.DirectDependencies++
		}
	}
	return stats
}

// uploadToS3 writes data to the specified S3 key.
func (g *Generator) uploadToS3(
	ctx context.Context,
	bucket, key string,
	data []byte,
) error {
	contentType := "application/json"
	_, err := g.s3Client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      &bucket,
		Key:         &key,
		Body:        bytes.NewReader(data),
		ContentType: &contentType,
	})
	return err
}
