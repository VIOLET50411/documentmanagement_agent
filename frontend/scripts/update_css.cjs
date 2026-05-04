const fs = require('fs');
const file = 'c:/Users/32020/Desktop/documentmanagement_agent/frontend/src/assets/css/index.css';
let content = fs.readFileSync(file, 'utf8');

// Replace body background
content = content.replace(/body \{[\s\S]*?\}/g, (match) => {
  if (match.includes('font-family')) {
    return 'body {\n  font-family: var(--font-family);\n  font-size: var(--text-base);\n  font-weight: 400;\n  color: var(--text-primary);\n  background: var(--bg-app);\n  line-height: 1.6;\n}';
  }
  return match;
});

// Replace dark theme background
content = content.replace(/html\.theme-dark body, \.theme-dark body \{[\s\S]*?\}/, 'html.theme-dark body, .theme-dark body {\n  background: var(--bg-app);\n}');

// Replace card
content = content.replace(/\.card, \.card-shell \{[\s\S]*?\}/, '.card, .card-shell {\n  background: var(--bg-surface);\n  border: 1px solid var(--border-color);\n  border-radius: var(--radius-lg);\n  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02), 0 4px 12px rgba(0, 0, 0, 0.02);\n  transition: box-shadow var(--transition-fast);\n}');

// Replace dark theme card
content = content.replace(/\.theme-dark \.card, \.theme-dark \.card-shell \{[\s\S]*?\}/, '.theme-dark .card, .theme-dark .card-shell {\n  border: 1px solid var(--border-color);\n  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);\n}');

// Replace input
content = content.replace(/\.input \{[\s\S]*?\}/, '.input {\n  width: 100%;\n  padding: 10px 14px;\n  font-size: 0.95rem;\n  color: var(--text-primary);\n  background: var(--bg-input);\n  border: 1px solid var(--border-color);\n  border-radius: 8px;\n  outline: none;\n  line-height: 1.5;\n  transition: all var(--transition-fast);\n  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);\n}');

// Replace input focus
content = content.replace(/\.input:focus \{[\s\S]*?\}/, '.input:focus {\n  border-color: var(--color-primary);\n  box-shadow: 0 0 0 3px var(--color-primary-soft);\n  background: var(--bg-input);\n}');

// Add custom select styles at the end
if (!content.includes('select.input')) {
  content += `\nselect.input {\n  appearance: none;\n  background-image: url('data:image/svg+xml;utf8,<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="%238f8e8a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>');\n  background-repeat: no-repeat;\n  background-position: right 14px center;\n  padding-right: 40px;\n}\n.theme-dark select.input {\n  background-image: url('data:image/svg+xml;utf8,<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="%2375746f" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>');\n}\n`;
}

// Light theme colors
content = content.replace(/--bg-app: #f4f5f7;/g, '--bg-app: #fbfbfc;');
content = content.replace(/--bg-app-accent: #ebe9e2;/g, '--bg-app-accent: #f4f5f5;');
content = content.replace(/--bg-surface: rgba\(255, 255, 255, 0\.45\);/g, '--bg-surface: #ffffff;');
content = content.replace(/--bg-surface-strong: rgba\(255, 255, 255, 0\.7\);/g, '--bg-surface-strong: #f0f0f0;');
content = content.replace(/--bg-surface-hover: rgba\(255, 255, 255, 0\.3\);/g, '--bg-surface-hover: #f7f7f7;');
content = content.replace(/--bg-sidebar: rgba\(255, 255, 255, 0\.45\);/g, '--bg-sidebar: #fbfbfc;');
content = content.replace(/--bg-input: rgba\(255, 255, 255, 0\.6\);/g, '--bg-input: #ffffff;');

// Dark theme colors
content = content.replace(/--bg-app: #18181b;/g, '--bg-app: #121212;');
content = content.replace(/--bg-app-accent: #1c1b1a;/g, '--bg-app-accent: #1e1e1e;');
content = content.replace(/--bg-surface: rgba\(39, 39, 42, 0\.45\);/g, '--bg-surface: #1e1e1e;');
content = content.replace(/--bg-surface-strong: rgba\(63, 63, 70, 0\.4\);/g, '--bg-surface-strong: #2c2c2c;');
content = content.replace(/--bg-surface-hover: rgba\(63, 63, 70, 0\.3\);/g, '--bg-surface-hover: #2a2a2a;');
content = content.replace(/--bg-sidebar: rgba\(24, 24, 27, 0\.5\);/g, '--bg-sidebar: #121212;');
content = content.replace(/--bg-input: rgba\(0, 0, 0, 0\.3\);/g, '--bg-input: #1e1e1e;');

// Remove the `background-image` rule for `.theme-dark body` since I want it flat.
content = content.replace(/html\.theme-dark body, \.theme-dark body \{[\s\S]*?\}/, 'html.theme-dark body, .theme-dark body {\n  background: var(--bg-app);\n}');

// Update box-shadow variables for standard cards
content = content.replace(/--shadow-md: 0 4px 12px rgba\(0, 0, 0, 0\.05\);/g, '--shadow-md: 0 1px 3px rgba(0, 0, 0, 0.02), 0 4px 12px rgba(0, 0, 0, 0.02);');
content = content.replace(/--shadow-lg: 0 12px 32px rgba\(0, 0, 0, 0\.08\);/g, '--shadow-lg: 0 4px 24px rgba(0, 0, 0, 0.04);');

// Write back
fs.writeFileSync(file, content);
console.log('CSS updated successfully.');
