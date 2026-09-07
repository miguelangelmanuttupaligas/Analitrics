# Image Lock

Los despliegues de Analitrics usan digests OCI para que un mismo commit ejecute
los mismos artefactos en local y produccion. Los servicios propios se construyen
desde este repositorio y sus imagenes base tambien estan fijadas por digest.

| Componente | Referencia fijada |
| --- | --- |
| Phoenix | `arizephoenix/phoenix@sha256:5ae3c414e8ee7ee47caa022edf8e94bdef7a90634a4e914a99dbe9d1f70790b8` |
| Keycloak | `quay.io/keycloak/keycloak@sha256:f1f1f01e472c8a78df40d8f2a49a925274eda4d3d80d5f6edbb5c880ee3c01c6` |
| RustFS | `rustfs/rustfs@sha256:41fe89380f4120a337790c02af192c3fe7bb55c3edc2e6e9357b487b47c6ab21` |
| LibreChat RAG API | `registry.librechat.ai/danny-avila/librechat-rag-api-dev-lite@sha256:c0ad82657b556c1e16dcfca85d045788f67caa223e25e70eb687f4d16b41dedc` |
| LibreChat admin panel | `registry.librechat.ai/clickhouse/librechat-admin-panel@sha256:a395465d1daa3c11495810a8c224df86675985d50de42e98e36eeedbd8aecb94` |

Para actualizar una dependencia se debe cambiar intencionalmente su digest,
validar el despliegue local y promover el commit. No se usa `latest` en los
servicios que forman parte de la plataforma.
