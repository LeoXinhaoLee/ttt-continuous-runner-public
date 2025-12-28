#!/bin/bash

# docker build -f docker/amd-docker.Dockerfile -t ghcr.io/leoxinhaolee/amd-runner:latest . 

GITHUB_TOKEN=

echo "$GITHUB_TOKEN" | docker login ghcr.io -u LeoXinhaoLee --password-stdin

docker push ghcr.io/leoxinhaolee/amd-runner:latest

