# terraform-ci

WIP

Fill out the secrets.env with your variables.

Expects a repo to be available somewhere and mounted in `docker-compose.yml`,
with e.g.:
```
terraform
  ^-- aws
  ^-- gcp
```
Currently only supports AWS and GCP, and currently only supports processing
changes for one of those at a time in commits.

Should be running on a secret instance.
