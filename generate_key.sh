#!/bin/bash

# Utility script to generate configuration secrets. Each key is 32 random
# alphanumeric characters. Existing values can be replaced interactively.

generate_and_set() {
  local name="$1"
  local value=$(tr -dc 'a-zA-Z0-9' </dev/urandom | fold -w 32 | head -n 1)

  if grep -q "${name}:" config.yaml; then
    echo "A ${name} is already present in the config.yaml file."
    echo "Note: Updating the ${name} may cause loss of old data."
    read -p "Are you sure you want to update the ${name}? (y/n): " confirm
    case "${confirm}" in
      y|Y)
        sed -i "s/${name}:.*/${name}: \"${value}\"/" config.yaml
        echo "${name} has been updated in config.yaml"
        ;;
      *)
        echo "${name} update has been cancelled."
        ;;
    esac
  else
    echo "${name}: \"${value}\"" >> config.yaml
    echo "${name} has been set in config.yaml"
  fi
}

generate_and_set secret_key
generate_and_set initial_admin_password
generate_and_set encryption_key
generate_and_set encryption_salt
