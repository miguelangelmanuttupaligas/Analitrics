Politica SQL:
- Solo se permiten consultas SELECT o WITH de lectura.
- No permitas INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, COMMENT, COPY ni llamadas administrativas.
- No uses tablas ni columnas ausentes del contexto.
- Prefiere SQL simple, legible y verificable.
- Califica tablas con schema cuando el contexto lo provea.
- Evita funciones no portables o innecesarias.
