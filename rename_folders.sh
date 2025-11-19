#!/bin/bash

# Exit on any error
set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <folder-path>"
  exit 1
fi

ROOT="$1"

# macOS-compatible: use BSD find with -depth
find "$ROOT" -depth -name "*_*" | while IFS= read -r item; do
  
  dir="$(dirname "$item")"
  base="$(basename "$item")"
  newbase="$(echo "$base" | tr '_' '-')"
  newpath="$dir/$newbase"

  if [ "$item" != "$newpath" ]; then
    mv "$item" "$newpath"
    echo "Renamed: $item -> $newpath"
  fi

done

echo "Done!"