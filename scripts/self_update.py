#!/bin/bash
# Wrapper to update ocas-finch (fellow)
cd "/root/.hermes/skills/ocas-finch" || exit 1
git reset --hard HEAD 2>/dev/null
git clean -fd 2>/dev/null
git pull 2>/dev/null
