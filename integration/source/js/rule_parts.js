  // [integration] Invoiced parts are compared with the parts seen on the photos through one canonical name
  // per part, French or English (the visual agent answers in French, invoices are often in English).
  // Only lines of type "part" are compared: paint, consumables and fees (type "other") are never on a photo.
  const PART_NAMES = [
    ['bumper', /\b(bumpers?|pare[- ]?chocs?)\b/],
    ['bonnet', /\b(bonnet|hood|capot)\b/],
    ['wing', /\b(wings?|fenders?|ailes?|quarter panels?)\b/],
    ['door', /\b(doors?|portes?|portieres?)\b/],
    ['boot', /\b(boot|trunk|tailgate|boot lid|trunk lid|coffre|hayon)\b/],
    ['headlight', /\b(head ?lights?|head ?lamps?|phares?|projecteurs?|optiques? avant)\b/],
    ['tail light', /\b(tail ?lights?|rear lights?|feux? arriere|optiques? arriere)\b/],
    ['fog light', /\b(fog ?lights?|fog ?lamps?|antibrouillards?)\b/],
    ['grille', /\b(grille|calandre)\b/],
    ['mirror', /\b(mirrors?|retroviseurs?)\b/],
    ['windscreen', /\b(windscreen|windshield|pare[- ]?brise)\b/],
    ['rear window', /\b(rear window|rear screen|lunette arriere)\b/],
    ['side window', /\b(side windows?|vitres?|glaces? laterales?)\b/],
    ['radiator', /\b(radiators?|radiateurs?)\b/],
    ['wheel', /\b(wheels?|rims?|jantes?|roues?)\b/],
    ['tyre', /\b(tyres?|tires?|pneus?)\b/],
    ['roof', /\b(roof|toit|pavillon)\b/],
    ['sill', /\b(sills?|rocker panels?|bas de caisse)\b/],
  ];
  // front / rear is kept: a rear bumper on the photos does not make a front bumper on the invoice visible
  const position = (t) => /\b(front|avant|av)\b/.test(t) ? 'front' : /\b(rear|back|arriere|ar)\b/.test(t) ? 'rear' : null;
  const canon = (s) => {
    const t = norm(s);
    const pos = position(t);
    const hits = PART_NAMES.filter(([, re]) => re.test(t)).map(([k]) => ({ key: k, pos: k === 'tail light' || k === 'rear window' ? 'rear' : pos }));
    return hits.length ? hits : [{ key: t, pos, raw: true }];
  };
  const same = (a, b) => (a.raw || b.raw ? (a.key.includes(b.key) || b.key.includes(a.key)) : a.key === b.key)
    && !(a.pos && b.pos && a.pos !== b.pos);
  const seen = (v.damaged_parts || []).flatMap(canon);
  const notVisible = (inv.line_items || [])
    .filter(li => li.part && li.type === 'part')
    .filter(li => !canon(li.part).some(p => seen.some(s => same(p, s))))
    .map(li => li.part);
