const fs = require('fs');
const file = 'c:/Users/32020/Desktop/documentmanagement_agent/frontend/src/assets/css/index.css';
let content = fs.readFileSync(file, 'utf8');

if (!content.includes('.data-table {')) {
  content += `\n/* Premium Data Table */\n.data-table {\n  width: 100%;\n  border-collapse: separate;\n  border-spacing: 0;\n}\n\n.data-table th,\n.data-table td {\n  padding: 14px 12px;\n  text-align: left;\n  border-bottom: 1px solid var(--border-color-subtle);\n  vertical-align: middle;\n}\n\n.data-table th {\n  font-size: 0.76rem;\n  font-weight: 500;\n  text-transform: uppercase;\n  letter-spacing: 0.08em;\n  color: var(--text-tertiary);\n}\n\n.data-table tr:hover td {\n  background-color: var(--bg-surface-hover);\n}\n`;
  fs.writeFileSync(file, content);
}
console.log("Appended .data-table");
