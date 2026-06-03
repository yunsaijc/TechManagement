const fs = require('fs');
const json = JSON.parse(fs.readFileSync('debug_review/batch_review_db832d940a2843e6b3c33970336d0e9e/index.html', 'utf-8').match(/const REPORT_DATA = (.*?);\n/)[1]);
let mixed = false;
json.data.items.forEach(p => {
  const sections = [...(p.policy_sections||[]), ...(p.extra_sections||[])];
  sections.forEach(s => {
    (s.groups||[]).forEach(g => {
      (g.items||[]).forEach(item => {
        const hasNav = item.evidence_targets?.some(t => Number(t.packet_page) > 0);
        const hasExp = item.evidence_targets?.some(t => !Number(t.packet_page) && String(t.viewer_mode) === 'explanation');
        if (hasNav && hasExp) {
          mixed = true;
          console.log('Mixed rule:', item.title);
        }
      });
    });
  });
});
console.log('Mixed?', mixed);
