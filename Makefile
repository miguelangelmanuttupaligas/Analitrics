SHELL := /usr/bin/env bash

STACKS := keycloak librechat phoenix
STACK := $(firstword $(filter $(STACKS),$(MAKECMDGOALS)))

.PHONY: keycloak librechat phoenix up down storage-metadata analitrics-build control-plane-migrate control-plane-grants analitrics-profile analitrics-nl-sql analitrics-agent prepare-dirs ensure-network cleanup-network help

keycloak librechat phoenix:
	@:

up down:
	@if [[ -z "$(STACK)" ]]; then \
		echo "Usage: make <keycloak|librechat> $@"; \
		exit 2; \
	fi
	@case "$(STACK)" in \
		keycloak) compose_dir="keycloak"; compose_project="keycloak" ;; \
		librechat) compose_dir="librechat/custom"; compose_project="librechat-src" ;; \
		phoenix) compose_dir="phoenix"; compose_project="phoenix" ;; \
	esac; \
	set -euo pipefail; \
	case "$@" in \
		up) if [[ "$(STACK)" == "phoenix" ]]; then \
				$(MAKE) --no-print-directory ensure-network; \
			else \
				$(MAKE) --no-print-directory prepare-dirs ensure-network; \
			fi; \
			if [[ "$(STACK)" == "librechat" ]]; then \
				docker compose --project-name "$$compose_project" --project-directory "$$compose_dir" -f "$$compose_dir/docker-compose.yml" up -d --build --remove-orphans; \
			else \
				docker compose --project-name "$$compose_project" --project-directory "$$compose_dir" -f "$$compose_dir/docker-compose.yml" up -d --remove-orphans; \
			fi; \
			if [[ "$(STACK)" == "librechat" ]]; then \
				for i in {1..30}; do docker exec analitrics-analitrics-mongodb mongosh LibreChat --quiet --eval 'db.adminCommand({ping:1}).ok' >/dev/null 2>&1 && break || sleep 1; done; \
				docker exec analitrics-analitrics-mongodb mongosh LibreChat --quiet --eval 'db.files.createIndex({tenantId:1,source:1,user:1,file_id:1,createdAt:-1},{name:"analitrics_files_owner_file"}); db.files.createIndex({tenantId:1,source:1,user:1,filename:1,createdAt:-1},{name:"analitrics_files_owner_filename"}); db.messages.createIndex({conversationId:1,messageId:1,createdAt:1},{name:"analitrics_messages_conversation_message"}); db.analitrics_agent_runs.createIndex({tenantId:1,userId:1,conversationId:1,createdAt:-1},{name:"analitrics_runs_conversation_recent"}); db.analitrics_agent_runs.createIndex({tenantId:1,userId:1,questionNormalized:1,createdAt:-1},{name:"analitrics_runs_question_search"}); printjson({ok:true,indexes:"analitrics"});'; \
				docker exec analitrics-analitrics-mongodb mongosh LibreChat --quiet --eval 'const locked={PROMPTS:{USE:false,CREATE:false,SHARE:false,SHARE_PUBLIC:false},AGENTS:{USE:true,CREATE:false,SHARE:false,SHARE_PUBLIC:false},RUN_CODE:{USE:false},WEB_SEARCH:{USE:false},MARKETPLACE:{USE:false},MCP_SERVERS:{USE:true,CREATE:false,SHARE:false,SHARE_PUBLIC:false,CONFIGURE_OBO:false},REMOTE_AGENTS:{USE:false,CREATE:false,SHARE:false,SHARE_PUBLIC:false},SKILLS:{USE:false,CREATE:false,SHARE:false,SHARE_PUBLIC:false}}; const res=db.roles.updateMany({name:{$$in:["USER","ADMIN"]}},{$$set:Object.fromEntries(Object.entries(locked).map(([k,v])=>["permissions."+k,v]))}); printjson({matched:res.matchedCount,modified:res.modifiedCount,locked:Object.keys(locked)});'; \
				docker exec analitrics-analitrics-mongodb mongosh LibreChat --quiet --eval 'const author=db.users.findOne({email:"analitrics.user@example.com"},{_id:1,email:1}); if(!author){printjson({ok:false,skipped:"agent_analitrics",reason:"author user not found"}); quit(0);} const viewer=db.accessroles.findOne({accessRoleId:"agent_viewer",resourceType:"agent"},{_id:1,permBits:1}); const owner=db.accessroles.findOne({accessRoleId:"agent_owner",resourceType:"agent"},{_id:1,permBits:1}); if(!viewer||!owner){throw new Error("agent access roles not found");} const now=new Date(); const existing=db.agents.findOne({id:"agent_analitrics"},{_id:1}); const agentId=existing?existing._id:new ObjectId(); db.agents.updateOne({id:"agent_analitrics"},{$$set:{_id:agentId,id:"agent_analitrics",name:"Analitrics",description:"Agente analítico único de Analitrics.",instructions:"Responde únicamente preguntas analíticas sobre los archivos cargados por el usuario.",provider:"openAI",model:"analitrics-agent",model_parameters:{},tools:[],tool_resources:{},author:author._id,category:"general",execute_code:false,file_search:false,web_search:false,is_promoted:true,tenantId:"analitrics",updatedAt:now},$$setOnInsert:{createdAt:now}},{upsert:true}); db.aclentries.updateOne({principalType:"public",resourceType:"agent",resourceId:agentId},{$$set:{permBits:viewer.permBits,roleId:viewer._id,grantedBy:author._id,grantedAt:now}},{upsert:true}); db.aclentries.updateOne({principalType:"user",principalId:author._id,principalModel:"User",resourceType:"agent",resourceId:agentId},{$$set:{permBits:owner.permBits,roleId:owner._id,grantedBy:author._id,grantedAt:now}},{upsert:true}); printjson({ok:true,id:"agent_analitrics",_id:agentId,publicPermBits:viewer.permBits,ownerPermBits:owner.permBits});'; \
			fi ;; \
		down) docker compose --project-name "$$compose_project" --project-directory "$$compose_dir" -f "$$compose_dir/docker-compose.yml" down --remove-orphans; $(MAKE) --no-print-directory cleanup-network ;; \
	esac

ensure-network:
	@docker network inspect network-analitrics >/dev/null 2>&1 || docker network create network-analitrics >/dev/null

cleanup-network:
	@docker network rm network-analitrics >/dev/null 2>&1 || true

storage-metadata:
	@docker exec analitrics-analitrics-mongodb mongosh LibreChat --quiet --eval 'const pad=(v,n)=>String(v??"").length>n?String(v??"").slice(0,n-1)+"…":String(v??"").padEnd(n); const fmtBytes=(b)=>{b=Number(b||0); if(b>=1048576)return (b/1048576).toFixed(1)+"MB"; if(b>=1024)return (b/1024).toFixed(1)+"KB"; return b+"B";}; const fmtDate=(d)=>d?d.toISOString().replace("T"," ").slice(0,19):""; const rows=db.files.find({source:"s3"},{_id:0,tenantId:1,filename:1,type:1,bytes:1,source:1,storageKey:1,createdAt:1}).sort({createdAt:-1}).toArray(); print([pad("BUCKET",10),pad("TENANT",12),pad("FILENAME",30),pad("TYPE",64),pad("SIZE",8),pad("SOURCE",8),pad("CREATED_AT",19),pad("STORAGE_KEY",80)].join("  ")); print("-".repeat(245)); rows.forEach((f)=>print([pad("librechat",10),pad(f.tenantId,12),pad(f.filename,30),pad(f.type,64),pad(fmtBytes(f.bytes),8),pad(f.source,8),pad(fmtDate(f.createdAt),19),pad(f.storageKey,80)].join("  ")))'

analitrics-build:
	@docker build -t analitrics-app:local analitrics-app

control-plane-migrate: ensure-network analitrics-build
	@docker run --rm --network network-analitrics --env-file librechat/custom/.env \
		-e ANALITRICS_POSTGRES_HOST=control-postgres \
		-e ANALITRICS_POSTGRES_PORT=5432 \
		analitrics-app:local -m alembic -c alembic.ini upgrade head

control-plane-grants: ensure-network analitrics-build
	@docker run --rm --network network-analitrics --env-file librechat/custom/.env \
		-e ANALITRICS_POSTGRES_HOST=control-postgres \
		-e ANALITRICS_POSTGRES_PORT=5432 \
		analitrics-app:local scripts/control_plane_permissions.py

analitrics-profile:
	@if [[ -z "$${FILE_ID:-}" && -z "$${FILENAME:-}" ]]; then \
		echo "Usage: FILE_ID=<file_id> make analitrics-profile"; \
		echo "   or: FILENAME=data_2024_2026.xlsx make analitrics-profile"; \
		exit 2; \
	fi
	@set -a; source <(grep -v '^UID=' librechat/custom/.env); set +a; \
	docker run --rm --user "$$(id -u):$$(id -g)" --network network-analitrics --add-host host.docker.internal:host-gateway --env-file librechat/custom/.env \
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
	@set -a; source <(grep -v '^UID=' librechat/custom/.env); set +a; \
	docker run --rm --user "$$(id -u):$$(id -g)" --network network-analitrics --add-host host.docker.internal:host-gateway --env-file librechat/custom/.env \
		-e MONGO_URI=mongodb://mongodb:27017/LibreChat \
		-e MONGO_DB=LibreChat \
		-e AWS_ENDPOINT_URL=http://storage-rustfs:9000 \
		-e AWS_BUCKET_NAME="$${RUSTFS_BUCKET_NAME:-librechat}" \
		analitrics-app:local scripts/nl_sql_file.py --mode nl-sql $${FILE_ID:+--file-id "$$FILE_ID"} $${FILENAME:+--filename "$$FILENAME"} --question "$$QUESTION"

analitrics-agent:
	@if [[ -z "$${QUESTION:-}" ]]; then \
		echo "Usage: QUESTION='pregunta...' CONVERSATION_ID=<conversation_id> FILE_ID=<file_id> make analitrics-agent"; \
		echo "   or: QUESTION='pregunta...' CONVERSATION_ID=<conversation_id> FILENAME=data_2024_2026.xlsx make analitrics-agent"; \
		echo "   or: QUESTION='pregunta...' CONVERSATION_ID=<conversation_id> FILE_IDS=id1,id2 make analitrics-agent"; \
		echo "   or: QUESTION='pregunta...' CONVERSATION_ID=<conversation_id> FILENAMES=a.xlsx,b.csv make analitrics-agent"; \
		exit 2; \
	fi
	@if [[ -z "$${CONVERSATION_ID:-}" ]]; then \
		echo "Usage: QUESTION='pregunta...' CONVERSATION_ID=<conversation_id> FILE_ID=<file_id> make analitrics-agent"; \
		echo "CONVERSATION_ID is required; Analitrics no longer accepts analysisSessionId or implicit sessions."; \
		exit 2; \
	fi
	@if [[ -z "$${FILE_ID:-}" && -z "$${FILENAME:-}" && -z "$${FILE_IDS:-}" && -z "$${FILENAMES:-}" ]]; then \
		echo "Usage: QUESTION='pregunta...' CONVERSATION_ID=<conversation_id> FILE_ID=<file_id> make analitrics-agent"; \
		echo "   or: QUESTION='pregunta...' CONVERSATION_ID=<conversation_id> FILENAME=data_2024_2026.xlsx make analitrics-agent"; \
		echo "   or: QUESTION='pregunta...' CONVERSATION_ID=<conversation_id> FILE_IDS=id1,id2 make analitrics-agent"; \
		echo "   or: QUESTION='pregunta...' CONVERSATION_ID=<conversation_id> FILENAMES=a.xlsx,b.csv make analitrics-agent"; \
		exit 2; \
	fi
	@if [[ ! -w /var/analitrics/analytics/cache ]]; then \
		echo "Missing writable cache directory: /var/analitrics/analytics/cache"; \
		echo "Run: make librechat up"; \
		exit 2; \
	fi
	@set -a; source <(grep -v '^UID=' librechat/custom/.env); set +a; \
	env_args=(); \
	[[ -n "$(ANALITRICS_CONVERSATION_PLANNER_MODEL)" ]] && env_args+=(-e "ANALITRICS_CONVERSATION_PLANNER_MODEL=$(ANALITRICS_CONVERSATION_PLANNER_MODEL)"); \
	[[ -n "$(ANALITRICS_NL_SQL_MODEL)" ]] && env_args+=(-e "ANALITRICS_NL_SQL_MODEL=$(ANALITRICS_NL_SQL_MODEL)"); \
	[[ -n "$(ANALITRICS_SQL_REPAIR_MODEL)" ]] && env_args+=(-e "ANALITRICS_SQL_REPAIR_MODEL=$(ANALITRICS_SQL_REPAIR_MODEL)"); \
	[[ -n "$(ANALITRICS_ANSWER_MODEL)" ]] && env_args+=(-e "ANALITRICS_ANSWER_MODEL=$(ANALITRICS_ANSWER_MODEL)"); \
	[[ -n "$(ANALITRICS_CRITIC_MODEL)" ]] && env_args+=(-e "ANALITRICS_CRITIC_MODEL=$(ANALITRICS_CRITIC_MODEL)"); \
	[[ -n "$(ANALITRICS_CHART_SPEC_MODEL)" ]] && env_args+=(-e "ANALITRICS_CHART_SPEC_MODEL=$(ANALITRICS_CHART_SPEC_MODEL)"); \
	docker run --rm --user "$$(id -u):$$(id -g)" --network network-analitrics --add-host host.docker.internal:host-gateway --env-file librechat/custom/.env \
		-e MONGO_URI=mongodb://mongodb:27017/LibreChat \
		-e MONGO_DB=LibreChat \
		-e AWS_ENDPOINT_URL=http://storage-rustfs:9000 \
		-e AWS_ACCESS_KEY_ID="$${RUSTFS_ANALYTICS_ACCESS_KEY_ID:-}" \
		-e AWS_SECRET_ACCESS_KEY="$${RUSTFS_ANALYTICS_SECRET_ACCESS_KEY:-}" \
		-e AWS_REGION="$${RUSTFS_REGION:-us-east-1}" \
		-e AWS_BUCKET_NAME="$${RUSTFS_BUCKET_NAME:-librechat}" \
		-e ANALITRICS_TRACING_ENABLED="$${ANALITRICS_TRACING_ENABLED:-true}" \
		-e ANALITRICS_DEBUG_LLM_STATS="$${ANALITRICS_DEBUG_LLM_STATS:-false}" \
		-e ANALITRICS_LLM_TIMEOUT_SECONDS="$${ANALITRICS_LLM_TIMEOUT_SECONDS:-120}" \
		-e ANALITRICS_LLM_PROVIDER="$(if $(ANALITRICS_LLM_PROVIDER),$(ANALITRICS_LLM_PROVIDER),$${ANALITRICS_LLM_PROVIDER:-openai})" \
		-e ANALITRICS_DEFAULT_MODEL="$(if $(ANALITRICS_DEFAULT_MODEL),$(ANALITRICS_DEFAULT_MODEL),$${ANALITRICS_DEFAULT_MODEL:-gpt-5.5})" \
		-e OTEL_EXPORTER_OTLP_ENDPOINT="$${OTEL_EXPORTER_OTLP_ENDPOINT:-http://phoenix:4317}" \
		-e PHOENIX_PROJECT_NAME="$${PHOENIX_PROJECT_NAME:-analitrics-mvp}" \
		-e PYTHONPATH=/app/scripts \
		-v /var/analitrics/analytics:/var/analitrics/analytics \
		"$${env_args[@]}" \
		analitrics-app:local -m analitrics_agent.cli $${FILE_ID:+--file-id "$$FILE_ID"} $${FILENAME:+--filename "$$FILENAME"} $${FILE_IDS:+--file-ids "$$FILE_IDS"} $${FILENAMES:+--filenames "$$FILENAMES"} $${USER_ID:+--user-id "$$USER_ID"} --conversation-id "$$CONVERSATION_ID" $${MESSAGE_ID:+--message-id "$$MESSAGE_ID"} --question "$$QUESTION"

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
		/var/analitrics/analytics/cache \
		/var/analitrics/analytics/postgresql \
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
		sudo mkdir -p /var/analitrics/analytics/{cache,postgresql}; \
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
	if [[ "$$(stat -c '%u:%g' /var/analitrics/analytics/postgresql)" != "70:70" ]]; then \
		sudo chown -R 70:70 /var/analitrics/analytics/postgresql; \
	fi; \
	if [[ "$$(stat -c '%u:%g' /var/analitrics/storage/data)" != "10001:10001" ]]; then \
		sudo chown -R 10001:10001 /var/analitrics/storage/data; \
	fi; \
	if [[ "$$(stat -c '%u:%g' /var/analitrics/storage/logs)" != "10001:10001" ]]; then \
		sudo chown -R 10001:10001 /var/analitrics/storage/logs; \
	fi; \
	local_owner="$$(id -u):$$(id -g)"; \
	for dir in /var/analitrics/librechat/{uploads,logs,skill,data,images,certs} /var/analitrics/analytics/cache; do \
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
	@echo "  QUESTION='pregunta...' FILE_IDS=id1,id2 make analitrics-agent"
	@echo "  QUESTION='pregunta...' FILENAMES=a.xlsx,b.csv CONVERSATION_ID=<id> make analitrics-agent"
