SHELL := /usr/bin/env bash

STACKS := keycloak librechat phoenix
STACK := $(firstword $(filter $(STACKS),$(MAKECMDGOALS)))

.PHONY: keycloak librechat phoenix up down storage-metadata analitrics-build analitrics-profile analitrics-nl-sql analitrics-agent prepare-dirs ensure-network cleanup-network help

keycloak librechat phoenix:
	@:

up down:
	@if [[ -z "$(STACK)" ]]; then \
		echo "Usage: make <keycloak|librechat> $@"; \
		exit 2; \
	fi
	@case "$(STACK)" in \
		keycloak) compose_dir="keycloak" ;; \
		librechat) compose_dir="librechat-src" ;; \
		phoenix) compose_dir="phoenix" ;; \
	esac; \
	case "$@" in \
		up) if [[ "$(STACK)" == "phoenix" ]]; then \
				$(MAKE) --no-print-directory ensure-network; \
			else \
				$(MAKE) --no-print-directory prepare-dirs ensure-network; \
			fi; \
			docker compose --project-directory "$$compose_dir" -f "$$compose_dir/docker-compose.yml" up -d --remove-orphans ;; \
		down) docker compose --project-directory "$$compose_dir" -f "$$compose_dir/docker-compose.yml" down --remove-orphans; $(MAKE) --no-print-directory cleanup-network ;; \
	esac

ensure-network:
	@docker network inspect network-analitrics >/dev/null 2>&1 || docker network create network-analitrics >/dev/null

cleanup-network:
	@docker network rm network-analitrics >/dev/null 2>&1 || true

storage-metadata:
	@docker exec analitrics-analitrics-mongodb mongosh LibreChat --quiet --eval 'const pad=(v,n)=>String(v??"").length>n?String(v??"").slice(0,n-1)+"…":String(v??"").padEnd(n); const fmtBytes=(b)=>{b=Number(b||0); if(b>=1048576)return (b/1048576).toFixed(1)+"MB"; if(b>=1024)return (b/1024).toFixed(1)+"KB"; return b+"B";}; const fmtDate=(d)=>d?d.toISOString().replace("T"," ").slice(0,19):""; const rows=db.files.find({source:"s3"},{_id:0,tenantId:1,filename:1,type:1,bytes:1,source:1,storageKey:1,createdAt:1}).sort({createdAt:-1}).toArray(); print([pad("BUCKET",10),pad("TENANT",12),pad("FILENAME",30),pad("TYPE",64),pad("SIZE",8),pad("SOURCE",8),pad("CREATED_AT",19),pad("STORAGE_KEY",80)].join("  ")); print("-".repeat(245)); rows.forEach((f)=>print([pad("librechat",10),pad(f.tenantId,12),pad(f.filename,30),pad(f.type,64),pad(fmtBytes(f.bytes),8),pad(f.source,8),pad(fmtDate(f.createdAt),19),pad(f.storageKey,80)].join("  ")))'

analitrics-build:
	@docker build -t analitrics-app:local analitrics-app

analitrics-profile:
	@if [[ -z "$${FILE_ID:-}" && -z "$${FILENAME:-}" ]]; then \
		echo "Usage: FILE_ID=<file_id> make analitrics-profile"; \
		echo "   or: FILENAME=data_2024_2026.xlsx make analitrics-profile"; \
		exit 2; \
	fi
	@docker run --rm --network network-analitrics --env-file librechat-src/.env \
		-e MONGO_URI=mongodb://mongodb:27017/LibreChat \
		-e MONGO_DB=LibreChat \
		-e AWS_ENDPOINT_URL=http://storage-rustfs:9000 \
		-e AWS_BUCKET_NAME="$${RUSTFS_BUCKET_NAME:-librechat}" \
		analitrics-app:local scripts/nl_sql_file.py --mode profile $${FILE_ID:+--file-id "$$FILE_ID"} $${FILENAME:+--filename "$$FILENAME"}

analitrics-nl-sql:
	@if [[ -z "$${QUESTION:-}" ]]; then \
		echo "Usage: QUESTION='pregunta...' FILE_ID=<file_id> make analitrics-nl-sql"; \
		echo "   or: QUESTION='pregunta...' FILENAME=data_2024_2026.xlsx make analitrics-nl-sql"; \
		exit 2; \
	fi
	@if [[ -z "$${FILE_ID:-}" && -z "$${FILENAME:-}" ]]; then \
		echo "Usage: QUESTION='pregunta...' FILE_ID=<file_id> make analitrics-nl-sql"; \
		echo "   or: QUESTION='pregunta...' FILENAME=data_2024_2026.xlsx make analitrics-nl-sql"; \
		exit 2; \
	fi
	@docker run --rm --network network-analitrics --env-file librechat-src/.env \
		-e MONGO_URI=mongodb://mongodb:27017/LibreChat \
		-e MONGO_DB=LibreChat \
		-e AWS_ENDPOINT_URL=http://storage-rustfs:9000 \
		-e AWS_BUCKET_NAME="$${RUSTFS_BUCKET_NAME:-librechat}" \
		analitrics-app:local scripts/nl_sql_file.py --mode nl-sql $${FILE_ID:+--file-id "$$FILE_ID"} $${FILENAME:+--filename "$$FILENAME"} --question "$$QUESTION"

analitrics-agent:
	@if [[ -z "$${QUESTION:-}" ]]; then \
		echo "Usage: QUESTION='pregunta...' FILE_ID=<file_id> make analitrics-agent"; \
		echo "   or: QUESTION='pregunta...' FILENAME=data_2024_2026.xlsx make analitrics-agent"; \
		exit 2; \
	fi
	@if [[ -z "$${FILE_ID:-}" && -z "$${FILENAME:-}" ]]; then \
		echo "Usage: QUESTION='pregunta...' FILE_ID=<file_id> make analitrics-agent"; \
		echo "   or: QUESTION='pregunta...' FILENAME=data_2024_2026.xlsx make analitrics-agent"; \
		exit 2; \
	fi
	@docker run --rm --network network-analitrics --env-file librechat-src/.env \
		-e MONGO_URI=mongodb://mongodb:27017/LibreChat \
		-e MONGO_DB=LibreChat \
		-e AWS_ENDPOINT_URL=http://storage-rustfs:9000 \
		-e AWS_BUCKET_NAME="$${RUSTFS_BUCKET_NAME:-librechat}" \
		-e ANALITRICS_TRACING_ENABLED="$${ANALITRICS_TRACING_ENABLED:-true}" \
		-e OTEL_EXPORTER_OTLP_ENDPOINT="$${OTEL_EXPORTER_OTLP_ENDPOINT:-http://phoenix:4317}" \
		-e PHOENIX_PROJECT_NAME="$${PHOENIX_PROJECT_NAME:-analitrics-mvp}" \
		analitrics-app:local scripts/agent_file.py $${FILE_ID:+--file-id "$$FILE_ID"} $${FILENAME:+--filename "$$FILENAME"} --question "$$QUESTION"

prepare-dirs:
	@set -euo pipefail; \
	dirs=( \
		/var/analitrics/librechat/mongodb \
		/var/analitrics/librechat/vectordb \
		/var/analitrics/librechat/uploads \
		/var/analitrics/librechat/logs \
		/var/analitrics/librechat/skill \
		/var/analitrics/librechat/data \
		/var/analitrics/librechat/images \
		/var/analitrics/librechat/certs \
		/var/analitrics/storage/data \
		/var/analitrics/storage/logs \
		/var/analitrics/keycloak/postgresql \
		/var/analitrics/keycloak/certs \
		/var/analitrics/observability/phoenix \
	); \
	for dir in "$${dirs[@]}"; do \
		if [[ ! -d "$$dir" ]]; then needs_mkdir=1; break; fi; \
	done; \
	if [[ "$${needs_mkdir:-0}" == "1" ]]; then \
		sudo mkdir -p /var/analitrics/librechat/{mongodb,vectordb,uploads,logs,skill,data,images,certs}; \
		sudo mkdir -p /var/analitrics/storage/{data,logs}; \
		sudo mkdir -p /var/analitrics/keycloak/{postgresql,certs}; \
		sudo mkdir -p /var/analitrics/observability/phoenix; \
	fi; \
	for dir in "$${dirs[@]}"; do \
		test -d "$$dir"; \
	done; \
	if [[ "$$(stat -c '%u:%g' /var/analitrics/librechat/mongodb)" != "999:999" ]]; then \
		sudo chown -R 999:999 /var/analitrics/librechat/mongodb; \
	fi; \
	if [[ "$$(stat -c '%u:%g' /var/analitrics/keycloak/postgresql)" != "70:70" ]]; then \
		sudo chown -R 70:70 /var/analitrics/keycloak/postgresql; \
	fi; \
	local_owner="$$(id -u):$$(id -g)"; \
	for dir in /var/analitrics/librechat/{uploads,logs,skill,data,images,certs} /var/analitrics/storage/{data,logs}; do \
		if [[ "$$(stat -c '%u:%g' "$$dir")" != "$$local_owner" ]]; then \
			sudo chown -R "$$local_owner" "$$dir"; \
		fi; \
	done

help:
	@echo "Usage:"
	@echo "  make keycloak up|down"
	@echo "  make librechat up|down"
	@echo "  make phoenix up|down"
	@echo "  make storage-metadata"
	@echo "  make analitrics-build"
	@echo "  FILE_ID=<file_id> make analitrics-profile"
	@echo "  QUESTION='pregunta...' FILE_ID=<file_id> make analitrics-nl-sql"
	@echo "  QUESTION='pregunta...' FILE_ID=<file_id> make analitrics-agent"
