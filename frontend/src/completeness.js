// The data-completeness gap vocabulary — the key facts the backend treats as
// the shape of a complete item, mirrored per item in every report/list row.
// One source so the Report's gap links and the Items ?missing= filter can't
// drift apart.

export const COMPLETENESS_LABELS = {
  value: 'Missing value',
  photo: 'Missing photo',
  location: 'Missing location',
  label: 'Missing label',
  warrantyDate: 'Missing warranty date',
  purchaseDate: 'Missing purchase date',
}

export function completenessLabel(key) {
  return COMPLETENESS_LABELS[key] || key
}
