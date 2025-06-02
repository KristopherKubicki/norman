#!/bin/bash

# Utility script to generate configuration secrets in the .env file. Each key is
# 32 random alphanumeric characters. Existing values can be replaced
# interactively.

generate_and_set() {
  local name="$1"
  local value=$(tr -dc 'a-zA-Z0-9' </dev/urandom | fold -w 32 | head -n 1)

  if grep -q "^${name}=" .env; then
    echo "${name} already exists in .env"
    echo "Note: Updating the ${name} may cause loss of old data."
    read -p "Are you sure you want to update the ${name}? (y/n): " confirm
    case "${confirm}" in
      y|Y)
        sed -i "s/^${name}=.*$/${name}=${value}/" .env
        echo "${name} updated in .env"
        ;;
      *)
        echo "${name} update has been cancelled."
        ;;
    esac
  else
    echo "${name}=${value}" >> .env
    echo "${name} added to .env"
  fi
}

generate_and_set secret_key
generate_and_set initial_admin_password
generate_and_set encryption_key
generate_and_set encryption_salt
