"""Immutable original build identity embedded in the source distribution or image.

BUILD_VERSION identifies the release channel/version that created this artifact;
it is not a mutable deployment tag. BUILD_REVISION identifies its source commit.
"""

BUILD_VERSION = "local-dev"
BUILD_REVISION = "unknown"