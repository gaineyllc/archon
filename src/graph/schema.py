"""
Archon Graph Ontology
─────────────────────
Node types, relationship types, and property definitions.
Used by both Kuzu and Neo4j backends to initialise the schema.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


# ── Node type constants ────────────────────────────────────────────────────────

class NodeType(str, Enum):
    FILE         = "File"
    DIRECTORY    = "Directory"
    PERSON       = "Person"
    LOCATION     = "Location"
    ORGANIZATION = "Organization"
    TOPIC        = "Topic"
    TAG          = "Tag"
    COLLECTION   = "Collection"
    EVENT        = "Event"
    MEDIA_ITEM   = "MediaItem"
    APPLICATION  = "Application"
    BINARY       = "Binary"
    VENDOR       = "Vendor"
    PRODUCT      = "Product"
    VERSION      = "Version"
    VULNERABILITY= "Vulnerability"
    LICENSE      = "License"
    DEPENDENCY   = "Dependency"
    CERTIFICATE  = "Certificate"
    FACE_CLUSTER = "FaceCluster"


class RelType(str, Enum):
    # Filesystem
    CHILD_OF          = "CHILD_OF"
    DUPLICATE_OF      = "DUPLICATE_OF"
    SIMILAR_TO        = "SIMILAR_TO"
    PART_OF           = "PART_OF"
    REFERENCES        = "REFERENCES"
    # Semantic
    MENTIONS          = "MENTIONS"
    TAGGED_WITH       = "TAGGED_WITH"
    LOCATED_AT        = "LOCATED_AT"
    OCCURRED_DURING   = "OCCURRED_DURING"
    # Visual
    DEPICTS           = "DEPICTS"
    CONTAINS_FACE     = "CONTAINS_FACE"
    # Media
    MATCHED_TO        = "MATCHED_TO"
    # Software
    IS_APPLICATION    = "IS_APPLICATION"
    IS_BINARY         = "IS_BINARY"
    MADE_BY           = "MADE_BY"
    IS_VERSION_OF     = "IS_VERSION_OF"
    DEPENDS_ON        = "DEPENDS_ON"
    LICENSED_UNDER    = "LICENSED_UNDER"
    HAS_VULNERABILITY = "HAS_VULNERABILITY"
    SIGNED_BY         = "SIGNED_BY"
    OWNS              = "OWNS"
    HAS_VERSION       = "HAS_VERSION"
    SUPERSEDES        = "SUPERSEDES"
    # Geography
    WITHIN            = "WITHIN"
    # Face
    SAME_PERSON_AS    = "SAME_PERSON_AS"


# ── Kuzu DDL ──────────────────────────────────────────────────────────────────

KUZU_NODE_DDL = """
CREATE NODE TABLE IF NOT EXISTS File (
    id          STRING,
    path        STRING,
    name        STRING,
    extension   STRING,
    size_bytes  INT64,
    created     DOUBLE,
    modified    DOUBLE,
    sha256      STRING,
    mime_type   STRING,
    protocol    STRING,
    host        STRING,
    share       STRING,
    file_category STRING,
    -- enrichment status
    indexed_at         DOUBLE,
    enrichment_status  STRING,
    -- common enriched
    summary     STRING,
    language    STRING,
    -- video
    container_format STRING,
    duration_secs    DOUBLE,
    overall_bitrate  INT64,
    video_codec      STRING,
    width            INT64,
    height           INT64,
    fps              DOUBLE,
    hdr_format       STRING,
    color_space      STRING,
    bit_depth        INT64,
    audio_codec      STRING,
    audio_channels   INT64,
    sample_rate      INT64,
    subtitle_languages STRING,
    -- image
    camera_make    STRING,
    camera_model   STRING,
    lens           STRING,
    focal_length   DOUBLE,
    aperture       DOUBLE,
    shutter_speed  STRING,
    iso            INT64,
    datetime_original DOUBLE,
    gps_latitude   DOUBLE,
    gps_longitude  DOUBLE,
    gps_altitude   DOUBLE,
    color_profile  STRING,
    -- document
    author         STRING,
    page_count     INT64,
    word_count     INT64,
    has_macros     BOOLEAN,
    is_encrypted   BOOLEAN,
    is_signed      BOOLEAN,
    contains_secrets BOOLEAN,
    secret_types   STRING,
    document_type  STRING,
    sentiment      STRING,
    -- audio
    artist         STRING,
    album          STRING,
    album_artist   STRING,
    year           INT64,
    genre          STRING,
    track_number   INT64,
    bpm            DOUBLE,
    musicbrainz_id STRING,
    acoustid       STRING,
    -- executable
    architecture   STRING,
    compiler       STRING,
    product_name   STRING,
    company_name   STRING,
    file_version   STRING,
    signed         BOOLEAN,
    signature_valid BOOLEAN,
    is_packed      BOOLEAN,
    entropy        DOUBLE,
    eol_status     STRING,
    latest_version STRING,
    version_behind INT64,
    cve_count      INT64,
    -- archive
    compression_method   STRING,
    compression_ratio    DOUBLE,
    file_count_in_archive INT64,
    contains_executables BOOLEAN,
    -- certificate
    cert_subject   STRING,
    cert_issuer    STRING,
    cert_valid_from DOUBLE,
    cert_valid_to  DOUBLE,
    cert_is_expired BOOLEAN,
    days_until_expiry INT64,
    cert_key_algorithm STRING,
    cert_fingerprint STRING,
    -- source code
    code_language  STRING,
    line_count     INT64,
    function_count INT64,
    -- pii
    pii_detected   BOOLEAN,
    pii_types      STRING,
    sensitivity_level STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Directory (
    id    STRING,
    path  STRING,
    name  STRING,
    host  STRING,
    share STRING,
    file_count  INT64,
    total_bytes INT64,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Person (
    id          STRING,
    name        STRING,
    face_cluster_id STRING,
    known       BOOLEAN,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS FaceCluster (
    id              STRING,
    label           STRING,
    face_count      INT64,
    representative_embedding STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Location (
    id        STRING,
    name      STRING,
    city      STRING,
    region    STRING,
    country   STRING,
    latitude  DOUBLE,
    longitude DOUBLE,
    place_type STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Organization (
    id   STRING,
    name STRING,
    type STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Topic (
    id   STRING,
    name STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Tag (
    id   STRING,
    name STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Collection (
    id          STRING,
    name        STRING,
    type        STRING,
    description STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Event (
    id         STRING,
    name       STRING,
    start_time DOUBLE,
    end_time   DOUBLE,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS MediaItem (
    id          STRING,
    title       STRING,
    type        STRING,
    year        INT64,
    tmdb_id     STRING,
    imdb_id     STRING,
    genre       STRING,
    director    STRING,
    rating      DOUBLE,
    poster_url  STRING,
    overview    STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Application (
    id              STRING,
    name            STRING,
    version_string  STRING,
    install_path    STRING,
    architecture    STRING,
    install_date    DOUBLE,
    last_run        DOUBLE,
    eol_status      STRING,
    eol_date        DOUBLE,
    latest_version  STRING,
    version_behind  INT64,
    update_available BOOLEAN,
    cve_count       INT64,
    critical_cve_count INT64,
    signed          BOOLEAN,
    source          STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Binary (
    id          STRING,
    path        STRING,
    name        STRING,
    sha256      STRING,
    architecture STRING,
    signed      BOOLEAN,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Vendor (
    id      STRING,
    name    STRING,
    website STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Product (
    id   STRING,
    name STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Version (
    id             STRING,
    version_string STRING,
    release_date   DOUBLE,
    is_lts         BOOLEAN,
    is_eol         BOOLEAN,
    eol_date       DOUBLE,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Vulnerability (
    id                  STRING,
    cve_id              STRING,
    cvss_score          DOUBLE,
    cvss_severity       STRING,
    description         STRING,
    published_date      DOUBLE,
    patched_in_version  STRING,
    exploit_available   BOOLEAN,
    actively_exploited  BOOLEAN,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS License (
    id   STRING,
    name STRING,
    spdx STRING,
    type STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Dependency (
    id      STRING,
    name    STRING,
    version STRING,
    PRIMARY KEY (id)
);

CREATE NODE TABLE IF NOT EXISTS Certificate (
    id              STRING,
    subject         STRING,
    issuer          STRING,
    serial          STRING,
    valid_from      DOUBLE,
    valid_to        DOUBLE,
    is_expired      BOOLEAN,
    days_until_expiry INT64,
    key_algorithm   STRING,
    key_size        INT64,
    fingerprint     STRING,
    is_ca           BOOLEAN,
    is_self_signed  BOOLEAN,
    PRIMARY KEY (id)
);
"""

KUZU_REL_DDL = """
CREATE REL TABLE IF NOT EXISTS CHILD_OF        (FROM File TO Directory, FROM Directory TO Directory);
CREATE REL TABLE IF NOT EXISTS DUPLICATE_OF    (FROM File TO File);
CREATE REL TABLE IF NOT EXISTS SIMILAR_TO      (FROM File TO File, score DOUBLE);
CREATE REL TABLE IF NOT EXISTS PART_OF         (FROM File TO Collection, FROM Application TO Product);
CREATE REL TABLE IF NOT EXISTS REFERENCES      (FROM File TO File);
CREATE REL TABLE IF NOT EXISTS MENTIONS        (FROM File TO Person, FROM File TO Organization, FROM File TO Topic);
CREATE REL TABLE IF NOT EXISTS TAGGED_WITH     (FROM File TO Tag);
CREATE REL TABLE IF NOT EXISTS LOCATED_AT      (FROM File TO Location);
CREATE REL TABLE IF NOT EXISTS OCCURRED_DURING (FROM File TO Event);
CREATE REL TABLE IF NOT EXISTS DEPICTS         (FROM File TO Person, FROM File TO Location);
CREATE REL TABLE IF NOT EXISTS CONTAINS_FACE   (FROM File TO FaceCluster, frame_offset DOUBLE, confidence DOUBLE);
CREATE REL TABLE IF NOT EXISTS MATCHED_TO      (FROM File TO MediaItem, confidence DOUBLE);
CREATE REL TABLE IF NOT EXISTS IS_APPLICATION  (FROM File TO Application);
CREATE REL TABLE IF NOT EXISTS IS_BINARY       (FROM File TO Binary);
CREATE REL TABLE IF NOT EXISTS MADE_BY         (FROM Application TO Vendor);
CREATE REL TABLE IF NOT EXISTS IS_VERSION_OF   (FROM Application TO Product);
CREATE REL TABLE IF NOT EXISTS DEPENDS_ON      (FROM Application TO Dependency, FROM Binary TO Dependency);
CREATE REL TABLE IF NOT EXISTS LICENSED_UNDER  (FROM Application TO License, FROM File TO License);
CREATE REL TABLE IF NOT EXISTS HAS_VULNERABILITY (FROM Application TO Vulnerability, FROM Dependency TO Vulnerability);
CREATE REL TABLE IF NOT EXISTS SIGNED_BY       (FROM Application TO Certificate, FROM Binary TO Certificate);
CREATE REL TABLE IF NOT EXISTS OWNS            (FROM Vendor TO Product);
CREATE REL TABLE IF NOT EXISTS HAS_VERSION     (FROM Product TO Version);
CREATE REL TABLE IF NOT EXISTS SUPERSEDES      (FROM Version TO Version);
CREATE REL TABLE IF NOT EXISTS WITHIN          (FROM Location TO Location);
CREATE REL TABLE IF NOT EXISTS SAME_PERSON_AS  (FROM FaceCluster TO Person, confidence DOUBLE);
"""
