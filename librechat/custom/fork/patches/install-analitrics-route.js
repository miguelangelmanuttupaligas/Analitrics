const fs = require('fs');

const routeFile = '/app/api/server/routes/analitrics.js';
fs.copyFileSync('/tmp/analitrics-fork/api/routes/analitrics.js', routeFile);

let routesIndex = fs.readFileSync('/app/api/server/routes/index.js', 'utf8');
if (!routesIndex.includes("const analitrics = require('./analitrics');")) {
  routesIndex = routesIndex.replace(
    "const actions = require('./actions');",
    "const actions = require('./actions');\nconst analitrics = require('./analitrics');",
  );
}
if (!routesIndex.includes('  analitrics,')) {
  routesIndex = routesIndex.replace('module.exports = {\n', 'module.exports = {\n  analitrics,\n');
}
fs.writeFileSync('/app/api/server/routes/index.js', routesIndex);

let serverIndex = fs.readFileSync('/app/api/server/index.js', 'utf8');
if (!serverIndex.includes("app.use('/api/analitrics', routes.analitrics);")) {
  serverIndex = serverIndex.replace(
    "  app.use('/api/convos', routes.convos);",
    "  app.use('/api/convos', routes.convos);\n  app.use('/api/analitrics', routes.analitrics);",
  );
}
fs.writeFileSync('/app/api/server/index.js', serverIndex);
