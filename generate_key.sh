#!/bin/bash

# Generate a random 32-character secret key using /dev/urandom
secret_key=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)

# Check if secret_key is already in the config.yaml file
grep -q "secret_key:" config.yaml

if [ $? -eq 0 ]; then
  # If secret_key is found, prompt the user to confirm updating the secret_key
  echo "A secret_key is already present in the config.yaml file."
  echo "Note: Updating the secret_key may cause loss of old data."
  read -p "Are you sure you want to update the secret_key? (y/n): " confirm

  case "$confirm" in
    y|Y)
      # If the user confirms, replace the existing value with the new secret_key
      sed -i "s/secret_key:.*/secret_key: \"${secret_key}\"/" config.yaml
      echo "Secret key has been updated in config.yaml"
      ;;
    *)
      echo "Secret key update has been cancelled."
      ;;
  esac
else
  # If secret_key is not found, append the secret_key to the config.yaml file
  echo "secret_key: \"${secret_key}\"" >> config.yaml
  echo "Secret key has been set in config.yaml"
fi
