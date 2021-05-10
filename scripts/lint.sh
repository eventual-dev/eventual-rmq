#!/bin/sh -e

export SOURCE_FILES="eventual_rmq tests"
set -x

autoflake --in-place --recursive $SOURCE_FILES
isort --project=eventual_rmq $SOURCE_FILES
black $SOURCE_FILES
