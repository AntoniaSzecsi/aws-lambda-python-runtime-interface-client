#!/bin/sh
# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Runs once per manylinux/musllinux container before cibuildwheel builds any
# wheel in it. Its only job is to make sure the toolchain that
# scripts/preinstall.sh needs is present, so that the vendored curl and
# aws-lambda-cpp sources compile for that platform.
#
# The dependency sources ship in deps/ inside the repository, so nothing is
# downloaded here when the image already carries the toolchain. That keeps wheel
# builds working on release runners with restricted network egress.
set -eu

# curl's buildconf needs the autotools chain; aws-lambda-cpp needs cmake.
REQUIRED="cmake make autoconf automake libtool m4 perl"

missing=""
for tool in $REQUIRED; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        # preinstall.sh accepts cmake3 as an alternative to cmake.
        if [ "$tool" = "cmake" ] && command -v cmake3 >/dev/null 2>&1; then
            continue
        fi
        missing="${missing}${missing:+ }${tool}"
    fi
done

if ! command -v c++ >/dev/null 2>&1 && ! command -v g++ >/dev/null 2>&1; then
    missing="${missing}${missing:+ }g++"
fi

if [ -z "$missing" ]; then
    echo "Build toolchain already present; nothing to install."
    exit 0
fi

echo "Missing build tools: ${missing}"

if command -v apk >/dev/null 2>&1; then
    # musllinux images are Alpine based.
    echo "Installing with apk."
    apk add --no-cache build-base cmake autoconf automake libtool m4 perl
elif command -v dnf >/dev/null 2>&1; then
    echo "Installing with dnf."
    dnf install -y gcc-c++ make cmake autoconf automake libtool m4 perl
elif command -v yum >/dev/null 2>&1; then
    echo "Installing with yum."
    yum install -y gcc-c++ make cmake autoconf automake libtool m4 perl
else
    echo "No supported package manager found and the toolchain is incomplete." >&2
    echo "Missing: ${missing}" >&2
    echo "Use a build image that ships these tools." >&2
    exit 1
fi

# Fail here rather than deep inside preinstall.sh with a confusing error.
for tool in $REQUIRED; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        if [ "$tool" = "cmake" ] && command -v cmake3 >/dev/null 2>&1; then
            continue
        fi
        echo "Still missing ${tool} after installing the toolchain." >&2
        exit 1
    fi
done

echo "Build toolchain ready."
