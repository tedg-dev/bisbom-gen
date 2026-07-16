/*
 * omnibor_java_intercept.c — LD_PRELOAD inline-hashing shim for Java.
 *
 * Design of record:
 *   docs/sidecar/java/inline-hashing-interception-design.md
 *   docs/sidecar/java/inline-hashing-explained.md
 *
 * Purpose
 * -------
 * In sidecar mode the CI/CD build phase is ephemeral: the workspace is
 * destroyed when the build job ends.  Every byte Phase 2 needs must be
 * captured *inside* the build.  This shim interposes libc file
 * finalization (close/rename/renameat) and, for each finalized .class
 * or .jar artifact, computes its git-blob SHA-1 (bomsh treedb topology
 * key) and SHA-256 gitoid (SBOM identity) inline — while the bytes are
 * still warm in the page cache — then appends one JSON event to the
 * capture log named by $OMNIBOR_CAPTURE_LOG.
 *
 * app/pipeline/java_capture.py:assemble_treedb() turns that log into the
 * exact bomsh treedb structure, so generate_adg() becomes an in-memory
 * assembly step instead of a post-build workspace rescan (no find, no
 * jar -xf, no re-hash).
 *
 * Sidecar constraints honoured:
 *   - The native build command, pom.xml/build.gradle are untouched; the
 *     shim is enabled purely via LD_PRELOAD + env (CI/CD YAML injection).
 *   - No source-tree writes; the shim only reads finalized artifacts and
 *     appends to the capture log.
 *
 * IMPORTANT — validation gate
 * ---------------------------
 * This file is compiled and validated on EC2 only (it cannot be built or
 * golden-validated offline).  See the design doc's open validation items
 * V1–V6: fd-table coverage under the JVM/Gradle daemon, temp-file rename
 * flows, in-memory JAR assembly, and byte-identical treedb vs the legacy
 * rescan.  Enable it via config only after V1–V6 pass on EC2.
 *
 * Build:
 *   gcc -shared -fPIC -O2 -o libomnibor_java_intercept.so \
 *       omnibor_java_intercept.c -ldl -lcrypto -lpthread -lz
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include <openssl/evp.h>
#include <zlib.h>

/* Forward declarations for the little-endian zip readers (defined
 * after append_jar_entries, which is their first user). */
static uint16_t be16_le(const unsigned char *p);
static uint32_t le32(const unsigned char *p);

/* ------------------------------------------------------------------ */
/* Real libc entry points (resolved lazily via RTLD_NEXT).            */
/* ------------------------------------------------------------------ */

static int (*real_close)(int) = NULL;
static int (*real_open)(const char *, int, ...) = NULL;
static int (*real_open64)(const char *, int, ...) = NULL;
static int (*real_openat)(int, const char *, int, ...) = NULL;
static int (*real_rename)(const char *, const char *) = NULL;
static int (*real_renameat)(int, const char *, int, const char *) = NULL;

static void init_reals(void)
{
    if (real_close)
        return;
    real_close = dlsym(RTLD_NEXT, "close");
    real_open = dlsym(RTLD_NEXT, "open");
    real_open64 = dlsym(RTLD_NEXT, "open64");
    real_openat = dlsym(RTLD_NEXT, "openat");
    real_rename = dlsym(RTLD_NEXT, "rename");
    real_renameat = dlsym(RTLD_NEXT, "renameat");
}

/* ------------------------------------------------------------------ */
/* fd -> path table for write-opened artifacts (mutex-guarded).       */
/* ------------------------------------------------------------------ */

#define FD_TABLE_MAX 4096

struct fd_entry {
    int fd;
    char *path;
};

static struct fd_entry fd_table[FD_TABLE_MAX];
static pthread_mutex_t fd_lock = PTHREAD_MUTEX_INITIALIZER;

static void fd_table_put(int fd, const char *path)
{
    pthread_mutex_lock(&fd_lock);
    for (int i = 0; i < FD_TABLE_MAX; i++) {
        if (fd_table[i].fd == 0 && fd_table[i].path == NULL) {
            fd_table[i].fd = fd;
            fd_table[i].path = strdup(path);
            break;
        }
    }
    pthread_mutex_unlock(&fd_lock);
}

/* Remove and return the tracked path for fd (caller frees). */
static char *fd_table_take(int fd)
{
    char *path = NULL;
    pthread_mutex_lock(&fd_lock);
    for (int i = 0; i < FD_TABLE_MAX; i++) {
        if (fd_table[i].fd == fd && fd_table[i].path != NULL) {
            path = fd_table[i].path;
            fd_table[i].fd = 0;
            fd_table[i].path = NULL;
            break;
        }
    }
    pthread_mutex_unlock(&fd_lock);
    return path;
}

/* ------------------------------------------------------------------ */
/* Artifact classification.                                           */
/* ------------------------------------------------------------------ */

enum artifact_kind { KIND_NONE, KIND_CLASS, KIND_JAR };

static int has_suffix(const char *s, const char *suffix)
{
    size_t ls = strlen(s), lf = strlen(suffix);
    return ls >= lf && strcmp(s + ls - lf, suffix) == 0;
}

static enum artifact_kind classify(const char *path)
{
    if (!path)
        return KIND_NONE;
    if (has_suffix(path, ".class"))
        return KIND_CLASS;
    if (has_suffix(path, ".jar") || has_suffix(path, ".war") ||
        has_suffix(path, ".ear"))
        return KIND_JAR;
    return KIND_NONE;
}

/* True if the path is under $OMNIBOR_BUILD_ROOT (when set). */
static int under_build_root(const char *path)
{
    const char *root = getenv("OMNIBOR_BUILD_ROOT");
    if (!root || !*root)
        return 1;
    return strncmp(path, root, strlen(root)) == 0;
}

/* ------------------------------------------------------------------ */
/* git-blob SHA-1 + SHA-256 gitoid, streamed in one pass.            */
/* ------------------------------------------------------------------ */

static void hex_encode(const unsigned char *raw, unsigned int len,
                       char *out)
{
    static const char *h = "0123456789abcdef";
    for (unsigned int i = 0; i < len; i++) {
        out[i * 2] = h[(raw[i] >> 4) & 0xF];
        out[i * 2 + 1] = h[raw[i] & 0xF];
    }
    out[len * 2] = '\0';
}

/*
 * Compute git-blob SHA-1 and SHA-256 of *path*.  Both use the git object
 * framing: digest("blob <size>\0" + file_bytes).  Returns 0 on success.
 */
static int hash_git_blob(const char *path, char *sha1_hex,
                         char *sha256_hex)
{
    struct stat st;
    if (stat(path, &st) != 0)
        return -1;

    FILE *f = fopen(path, "rb");
    if (!f)
        return -1;

    EVP_MD_CTX *c1 = EVP_MD_CTX_new();
    EVP_MD_CTX *c256 = EVP_MD_CTX_new();
    if (!c1 || !c256) {
        if (c1) EVP_MD_CTX_free(c1);
        if (c256) EVP_MD_CTX_free(c256);
        fclose(f);
        return -1;
    }
    EVP_DigestInit_ex(c1, EVP_sha1(), NULL);
    EVP_DigestInit_ex(c256, EVP_sha256(), NULL);

    char header[64];
    int hlen = snprintf(header, sizeof(header), "blob %lld",
                        (long long)st.st_size);
    /* include the terminating NUL byte in the digest */
    EVP_DigestUpdate(c1, header, (size_t)hlen + 1);
    EVP_DigestUpdate(c256, header, (size_t)hlen + 1);

    unsigned char buf[65536];
    size_t n;
    while ((n = fread(buf, 1, sizeof(buf), f)) > 0) {
        EVP_DigestUpdate(c1, buf, n);
        EVP_DigestUpdate(c256, buf, n);
    }
    fclose(f);

    unsigned char d1[EVP_MAX_MD_SIZE], d256[EVP_MAX_MD_SIZE];
    unsigned int l1 = 0, l256 = 0;
    EVP_DigestFinal_ex(c1, d1, &l1);
    EVP_DigestFinal_ex(c256, d256, &l256);
    EVP_MD_CTX_free(c1);
    EVP_MD_CTX_free(c256);

    hex_encode(d1, l1, sha1_hex);
    hex_encode(d256, l256, sha256_hex);
    return 0;
}

/* ------------------------------------------------------------------ */
/* Minimal .class parser: SourceFile attribute + this_class name.     */
/* Mirrors docker/patches/bomsh_java_fast_classreader.py.             */
/* ------------------------------------------------------------------ */

static uint16_t be16(const unsigned char *p) { return (p[0] << 8) | p[1]; }
static uint32_t be32(const unsigned char *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | p[3];
}

/*
 * Parse the constant pool to extract the SourceFile attribute value and
 * the fully-qualified class name (dotted).  On success writes into
 * source_file/class_name (both caller-provided buffers) and returns 0.
 * Best-effort: on any structural surprise it returns -1 and the caller
 * emits empty attributes (matching bomsh's tolerant behaviour).
 */
static int parse_class(const unsigned char *b, size_t len,
                       char *source_file, size_t sf_cap,
                       char *class_name, size_t cn_cap)
{
    source_file[0] = '\0';
    class_name[0] = '\0';
    if (len < 10 || be32(b) != 0xCAFEBABEu)
        return -1;

    size_t pos = 8;
    uint16_t cp_count = be16(b + pos);
    pos += 2;

    /* Offsets of UTF-8 entries and class-name indices, 1-based. */
    size_t *utf8_off = calloc(cp_count, sizeof(size_t));
    uint16_t *utf8_len = calloc(cp_count, sizeof(uint16_t));
    uint16_t *class_name_idx = calloc(cp_count, sizeof(uint16_t));
    if (!utf8_off || !utf8_len || !class_name_idx) {
        free(utf8_off); free(utf8_len); free(class_name_idx);
        return -1;
    }

    for (uint16_t i = 1; i < cp_count; i++) {
        if (pos >= len) goto fail;
        uint8_t tag = b[pos++];
        switch (tag) {
        case 1: { /* Utf8 */
            if (pos + 2 > len) goto fail;
            uint16_t l = be16(b + pos);
            pos += 2;
            if (pos + l > len) goto fail;
            utf8_off[i] = pos;
            utf8_len[i] = l;
            pos += l;
            break;
        }
        case 7: /* Class -> name_index (Utf8) */
            if (pos + 2 > len) goto fail;
            class_name_idx[i] = be16(b + pos);
            pos += 2;
            break;
        case 8:   /* String */
        case 16:  /* MethodType */
        case 19:  /* Module */
        case 20:  /* Package */
            pos += 2;
            break;
        case 15:  /* MethodHandle */
            pos += 3;
            break;
        case 3: case 4: case 9: case 10: case 11:
        case 12: case 17: case 18:
            pos += 4;
            break;
        case 5: case 6: /* Long/Double take two slots */
            pos += 8;
            i++;
            break;
        default:
            goto fail;
        }
    }

    if (pos + 6 > len) goto fail;
    pos += 2;                       /* access_flags */
    uint16_t this_class = be16(b + pos);
    pos += 2;                       /* this_class    */
    pos += 2;                       /* super_class   */

    /* interfaces */
    if (pos + 2 > len) goto fail;
    uint16_t ifaces = be16(b + pos);
    pos += 2 + (size_t)ifaces * 2;

    /* Resolve class name (internal '/' -> '.'). */
    if (this_class && this_class < cp_count) {
        uint16_t ni = class_name_idx[this_class];
        if (ni && ni < cp_count && utf8_off[ni]) {
            uint16_t l = utf8_len[ni];
            if (l >= cn_cap) l = cn_cap - 1;
            memcpy(class_name, b + utf8_off[ni], l);
            class_name[l] = '\0';
            for (uint16_t k = 0; k < l; k++)
                if (class_name[k] == '/') class_name[k] = '.';
        }
    }

    /* Skip fields then methods; each has its own attributes. */
    for (int section = 0; section < 2; section++) {
        if (pos + 2 > len) goto fail;
        uint16_t count = be16(b + pos);
        pos += 2;
        for (uint16_t m = 0; m < count; m++) {
            pos += 6;               /* access,name,descriptor */
            if (pos + 2 > len) goto fail;
            uint16_t nattr = be16(b + pos);
            pos += 2;
            for (uint16_t a = 0; a < nattr; a++) {
                if (pos + 6 > len) goto fail;
                pos += 2;           /* attribute_name_index */
                uint32_t alen = be32(b + pos);
                pos += 4 + alen;
            }
        }
    }

    /* Class-level attributes: find "SourceFile". */
    if (pos + 2 > len) goto fail;
    uint16_t nattr = be16(b + pos);
    pos += 2;
    for (uint16_t a = 0; a < nattr; a++) {
        if (pos + 6 > len) goto fail;
        uint16_t name_idx = be16(b + pos);
        pos += 2;
        uint32_t alen = be32(b + pos);
        pos += 4;
        if (name_idx < cp_count && utf8_off[name_idx]) {
            const unsigned char *nm = b + utf8_off[name_idx];
            uint16_t nl = utf8_len[name_idx];
            if (nl == 10 && memcmp(nm, "SourceFile", 10) == 0 &&
                alen == 2) {
                uint16_t sfi = be16(b + pos);
                if (sfi < cp_count && utf8_off[sfi]) {
                    uint16_t l = utf8_len[sfi];
                    if (l >= sf_cap) l = sf_cap - 1;
                    memcpy(source_file, b + utf8_off[sfi], l);
                    source_file[l] = '\0';
                }
            }
        }
        pos += alen;
    }

    free(utf8_off); free(utf8_len); free(class_name_idx);
    return 0;

fail:
    free(utf8_off); free(utf8_len); free(class_name_idx);
    return -1;
}

/* ------------------------------------------------------------------ */
/* Capture-log append (single write per event, O_APPEND-atomic).      */
/* ------------------------------------------------------------------ */

static void json_escape(const char *in, char *out, size_t cap)
{
    size_t o = 0;
    for (size_t i = 0; in[i] && o + 2 < cap; i++) {
        char c = in[i];
        if (c == '"' || c == '\\') {
            out[o++] = '\\';
            out[o++] = c;
        } else if (c == '\n' || c == '\r' || c == '\t') {
            /* drop control chars */
        } else {
            out[o++] = c;
        }
    }
    out[o] = '\0';
}

static void capture_append(const char *line)
{
    const char *log = getenv("OMNIBOR_CAPTURE_LOG");
    if (!log || !*log)
        return;
    int fd = real_open(log, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd < 0)
        return;
    ssize_t rc = write(fd, line, strlen(line));
    (void)rc;
    real_close(fd);
}

/* Read up to cap bytes of a file into buf; returns bytes read or -1. */
static ssize_t read_file(const char *path, unsigned char *buf, size_t cap)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return -1;
    size_t n = fread(buf, 1, cap, f);
    fclose(f);
    return (ssize_t)n;
}

/* ------------------------------------------------------------------ */
/* Finalization: hash + parse + emit one JSON event.                  */
/* ------------------------------------------------------------------ */

static void emit_class(const char *path, const char *sha1,
                       const char *gitoid)
{
    unsigned char buf[262144]; /* 256 KiB is ample for a .class */
    char sf[512] = "", cn[1024] = "";
    ssize_t n = read_file(path, buf, sizeof(buf));
    if (n > 0)
        parse_class(buf, (size_t)n, sf, sizeof(sf), cn, sizeof(cn));

    char esc_path[4096], esc_sf[1024], esc_cn[2048];
    json_escape(path, esc_path, sizeof(esc_path));
    json_escape(sf, esc_sf, sizeof(esc_sf));
    json_escape(cn, esc_cn, sizeof(esc_cn));

    char line[8192];
    snprintf(line, sizeof(line),
             "{\"kind\":\"class\",\"path\":\"%s\",\"sha1\":\"%s\","
             "\"gitoid\":\"%s\",\"source_file\":\"%s\","
             "\"class_name\":\"%s\"}\n",
             esc_path, sha1, gitoid, esc_sf, esc_cn);
    capture_append(line);
}

/*
 * Compute the git-blob SHA-1 of one JAR member from its *uncompressed*
 * bytes.  The member is located via its local-header offset (the local
 * header's own name/extra lengths are authoritative — they may differ
 * from the central-directory record).  STORED (0) and DEFLATE (8) are
 * supported; anything else (or a ZIP64/torn entry) returns -1 and the
 * caller emits the member name without a hash (Python falls back to
 * name correlation).  Returns 0 on success.
 */
static int hash_jar_member(FILE *f, uint32_t local_off, uint16_t method,
                           uint32_t comp_size, uint32_t usize,
                           char *sha1_hex)
{
    if (fseek(f, (long)local_off, SEEK_SET) != 0)
        return -1;
    unsigned char lh[30];
    if (fread(lh, 1, 30, f) != 30)
        return -1;
    if (!(lh[0] == 0x50 && lh[1] == 0x4b && lh[2] == 0x03 && lh[3] == 0x04))
        return -1;
    uint16_t lnlen = (uint16_t)(lh[26] | (lh[27] << 8));
    uint16_t lelen = (uint16_t)(lh[28] | (lh[29] << 8));
    if (fseek(f, (long)lnlen + lelen, SEEK_CUR) != 0)
        return -1;

    unsigned char *comp = malloc(comp_size ? comp_size : 1);
    if (!comp)
        return -1;
    if (comp_size && fread(comp, 1, comp_size, f) != comp_size) {
        free(comp);
        return -1;
    }

    unsigned char *raw = comp;
    int raw_owned = 0;
    if (method == 8) {
        raw = malloc(usize ? usize : 1);
        if (!raw) { free(comp); return -1; }
        raw_owned = 1;
        z_stream zs;
        memset(&zs, 0, sizeof(zs));
        if (inflateInit2(&zs, -MAX_WBITS) != Z_OK) {
            free(comp); free(raw); return -1;
        }
        zs.next_in = comp;
        zs.avail_in = comp_size;
        zs.next_out = raw;
        zs.avail_out = usize;
        int rc = inflate(&zs, Z_FINISH);
        inflateEnd(&zs);
        if ((rc != Z_STREAM_END && rc != Z_OK) || zs.total_out != usize) {
            free(comp); free(raw); return -1;
        }
    } else if (method != 0) {
        free(comp);
        return -1;
    }

    EVP_MD_CTX *c = EVP_MD_CTX_new();
    if (!c) { free(comp); if (raw_owned) free(raw); return -1; }
    EVP_DigestInit_ex(c, EVP_sha1(), NULL);
    char header[64];
    int hlen = snprintf(header, sizeof(header), "blob %u", usize);
    EVP_DigestUpdate(c, header, (size_t)hlen + 1);
    EVP_DigestUpdate(c, raw, usize);
    unsigned char d[EVP_MAX_MD_SIZE];
    unsigned int dl = 0;
    EVP_DigestFinal_ex(c, d, &dl);
    EVP_MD_CTX_free(c);
    hex_encode(d, dl, sha1_hex);

    free(comp);
    if (raw_owned) free(raw);
    return 0;
}

/*
 * List JAR central-directory members into a JSON "entries" array of
 * {"name": ..., "sha1": ...} objects.  Each .class member's git-blob
 * SHA-1 is computed from its uncompressed bytes so the Python assembler
 * correlates members to captured classes purely by content (matching
 * the legacy rescan's basename+content match).  A member whose bytes
 * cannot be hashed is emitted name-only for name-based fallback.
 */
static void append_jar_entries(const char *path, char *out, size_t cap)
{
    size_t o = 0;
    out[o++] = '[';

    FILE *f = fopen(path, "rb");
    if (!f) { out[o++] = ']'; out[o] = '\0'; return; }

    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); out[o++] = ']'; out[o] = '\0'; return; }
    long fsize = ftell(f);
    long scan = fsize < 65557 ? fsize : 65557; /* max EOCD + comment */
    long start = fsize - scan;
    if (start < 0) start = 0;

    unsigned char *tail = malloc((size_t)scan);
    if (!tail) { fclose(f); out[o++] = ']'; out[o] = '\0'; return; }
    fseek(f, start, SEEK_SET);
    size_t got = fread(tail, 1, (size_t)scan, f);

    /* Find End Of Central Directory signature 0x06054b50. */
    long eocd = -1;
    for (long i = (long)got - 22; i >= 0; i--) {
        if (tail[i] == 0x50 && tail[i + 1] == 0x4b &&
            tail[i + 2] == 0x05 && tail[i + 3] == 0x06) {
            eocd = i;
            break;
        }
    }
    if (eocd < 0) { free(tail); fclose(f); out[o++] = ']'; out[o] = '\0'; return; }

    uint16_t total = be16_le(tail + eocd + 10);
    uint32_t cd_off = le32(tail + eocd + 16);

    fseek(f, cd_off, SEEK_SET);
    int first = 1;
    for (uint16_t e = 0; e < total; e++) {
        unsigned char hdr[46];
        if (fread(hdr, 1, 46, f) != 46) break;
        if (!(hdr[0] == 0x50 && hdr[1] == 0x4b &&
              hdr[2] == 0x01 && hdr[3] == 0x02))
            break;
        uint16_t method = (uint16_t)(hdr[10] | (hdr[11] << 8));
        uint32_t comp_size = le32(hdr + 20);
        uint32_t usize = le32(hdr + 24);
        uint16_t nlen = hdr[28] | (hdr[29] << 8);
        uint16_t elen = hdr[30] | (hdr[31] << 8);
        uint16_t clen = hdr[32] | (hdr[33] << 8);
        uint32_t local_off = le32(hdr + 42);
        char name[1024];
        uint16_t rn = nlen < sizeof(name) - 1 ? nlen : sizeof(name) - 1;
        if (fread(name, 1, rn, f) != rn) break;
        name[rn] = '\0';
        if (nlen > rn) fseek(f, nlen - rn, SEEK_CUR);
        fseek(f, elen + clen, SEEK_CUR);
        long next_cd = ftell(f);

        if (!has_suffix(name, ".class"))
            continue;

        char msha[41];
        int have_sha = hash_jar_member(f, local_off, method,
                                       comp_size, usize, msha) == 0;
        fseek(f, next_cd, SEEK_SET);

        char esc[1200];
        json_escape(name, esc, sizeof(esc));
        char obj[1400];
        if (have_sha)
            snprintf(obj, sizeof(obj),
                     "%s{\"name\":\"%s\",\"sha1\":\"%s\"}",
                     first ? "" : ",", esc, msha);
        else
            snprintf(obj, sizeof(obj), "%s{\"name\":\"%s\"}",
                     first ? "" : ",", esc);
        size_t need = strlen(obj);
        if (o + need + 2 >= cap) break;
        memcpy(out + o, obj, need);
        o += need;
        first = 0;
    }

    free(tail);
    fclose(f);
    out[o++] = ']';
    out[o] = '\0';
}

static void emit_jar(const char *path, const char *sha1,
                     const char *gitoid)
{
    char esc_path[4096];
    json_escape(path, esc_path, sizeof(esc_path));

    char *entries = malloc(1 << 20); /* 1 MiB for entry list */
    if (!entries)
        return;
    append_jar_entries(path, entries, 1 << 20);

    size_t need = strlen(entries) + 8192;
    char *line = malloc(need);
    if (line) {
        snprintf(line, need,
                 "{\"kind\":\"jar\",\"path\":\"%s\",\"sha1\":\"%s\","
                 "\"gitoid\":\"%s\",\"entries\":%s}\n",
                 esc_path, sha1, gitoid, entries);
        capture_append(line);
        free(line);
    }
    free(entries);
}

static void finalize(const char *path)
{
    if (!path || !under_build_root(path))
        return;
    enum artifact_kind kind = classify(path);
    if (kind == KIND_NONE)
        return;

    char sha1[41], sha256[65];
    if (hash_git_blob(path, sha1, sha256) != 0)
        return;

    if (kind == KIND_CLASS)
        emit_class(path, sha1, sha256);
    else
        emit_jar(path, sha1, sha256);
}

/* little-endian helpers used by the zip reader */
static uint16_t be16_le(const unsigned char *p)
{
    return (uint16_t)(p[0] | (p[1] << 8));
}
static uint32_t le32(const unsigned char *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* ------------------------------------------------------------------ */
/* Interposed libc entry points.                                      */
/* ------------------------------------------------------------------ */

static int is_write_open(int flags)
{
    int acc = flags & O_ACCMODE;
    return acc == O_WRONLY || acc == O_RDWR;
}

static void track_if_target(int fd, const char *path, int flags)
{
    if (fd >= 0 && is_write_open(flags) &&
        classify(path) != KIND_NONE)
        fd_table_put(fd, path);
}

int open(const char *path, int flags, ...)
{
    init_reals();
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap; va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    int fd = real_open(path, flags, mode);
    track_if_target(fd, path, flags);
    return fd;
}

int open64(const char *path, int flags, ...)
{
    init_reals();
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap; va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    int fd = real_open64 ? real_open64(path, flags, mode)
                         : real_open(path, flags, mode);
    track_if_target(fd, path, flags);
    return fd;
}

int openat(int dirfd, const char *path, int flags, ...)
{
    init_reals();
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap; va_start(ap, flags);
        mode = (mode_t)va_arg(ap, int);
        va_end(ap);
    }
    int fd = real_openat(dirfd, path, flags, mode);
    /* Only absolute paths are tracked directly; relative openat paths
     * are resolved by the finalize()-on-rename flow instead. */
    if (path && path[0] == '/')
        track_if_target(fd, path, flags);
    return fd;
}

int close(int fd)
{
    init_reals();
    char *path = fd_table_take(fd);
    int rc = real_close(fd);
    if (path) {
        if (rc == 0)
            finalize(path);
        free(path);
    }
    return rc;
}

int rename(const char *oldp, const char *newp)
{
    init_reals();
    int rc = real_rename(oldp, newp);
    if (rc == 0)
        finalize(newp);
    return rc;
}

int renameat(int oldfd, const char *oldp, int newfd, const char *newp)
{
    init_reals();
    int rc = real_renameat(oldfd, oldp, newfd, newp);
    if (rc == 0 && newp && newp[0] == '/')
        finalize(newp);
    return rc;
}
