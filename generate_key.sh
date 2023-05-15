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

# Generate a random 32-character secret key using /dev/urandom
initial_admin_password=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)

# Check if initial_admin_passsword is already in the config.yaml file
grep -q "initial_admin_password:" config.yaml

if [ $? -eq 0 ]; then
  # If initial_admin_password is found, prompt the user to confirm updating the initial_admin_password
  echo "A initial_admin_password is already present in the config.yaml file."
  echo "Note: Updating the initial_admin_password may cause loss of old data."
  read -p "Are you sure you want to update the initial_admin_password? (y/n): " confirm

  case "$confirm" in
    y|Y)
      # If the user confirms, replace the existing value with the new initial_admin_password
      sed -i "s/initial_admin_password:.*/initial_admin_password: \"${initial_admin_password}\"/" config.yaml
      echo "Secret key has been updated in config.yaml"
      ;;
    *)
      echo "Secret key update has been cancelled."
      ;;
  esac
else
  # If initial_admin_password is not found, append the initial_admin_password to the config.yaml file
  echo "initial_admin_password: \"${initial_admin_password}\"" >> config.yaml
  echo "Secret key has been set in config.yaml"
fi


# Generate a random 32-character secret key using /dev/urandom
encryption_key=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)

# Check if initial_admin_passsword is already in the config.yaml file
grep -q "encryption_key:" config.yaml

if [ $? -eq 0 ]; then
  # If initial_admin_password is found, prompt the user to confirm updating the initial_admin_password
  echo "A initial encryption_key is already present in the config.yaml file."
  echo "Note: Updating the encryption key will cause loss of old data."
  read -p "Are you sure you want to update the encryption_key? (y/n): " confirm

  case "$confirm" in
    y|Y)
      # If the user confirms, replace the existing value with the new initial_admin_password
      sed -i "s/encryption_key:.*/encryption_key: \"${encryption_key}\"/" config.yaml
      echo "Secret key has been updated in config.yaml"
      ;;
    *)
      echo "Secret key update has been cancelled."
      ;;
  esac
else
  # If encryption_key is not found, append the encryption_key to the config.yaml file
  echo "encryption_key: \"${encryption_key}\"" >> config.yaml
  echo "Secret key has been set in config.yaml"
fi

# Generate a random 32-character secret key using /dev/urandom
encryption_salt=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)

# Check if initial_admin_passsword is already in the config.yaml file
grep -q "encryption_salt:" config.yaml

if [ $? -eq 0 ]; then
  # If initial_admin_password is found, prompt the user to confirm updating the initial_admin_password
  echo "A initial encryption_salt is already present in the config.yaml file."
  echo "Note: Updating the encryption key will cause loss of old data."
  read -p "Are you sure you want to update the encryption_salt? (y/n): " confirm

  case "$confirm" in
    y|Y)
      # If the user confirms, replace the existing value with the new initial_admin_password
      sed -i "s/encryption_salt:.*/encryption_salt: \"${encryption_salt}\"/" config.yaml
      echo "Secret key has been updated in config.yaml"
      ;;
    *)
      echo "Secret key update has been cancelled."
      ;;
  esac
else
  # If encryption_salt is not found, append the encryption_salt to the config.yaml file
  echo "encryption_salt: \"${encryption_salt}\"" >> config.yaml
  echo "Secret key has been set in config.yaml"
fi

