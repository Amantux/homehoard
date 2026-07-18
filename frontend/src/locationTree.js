// Helpers for turning the flat /locations list into a navigable site tree.
// Every location in the flat list carries its immediate `parent` ({id,name}),
// and the list is complete, so we can reconstruct full ancestry from it.

export function indexById(locations) {
  const byId = {}
  for (const loc of locations) byId[loc.id] = loc
  return byId
}

// Attach a `children` array to each node and return the roots (parent === null),
// each sorted by name. Non-destructive: works on shallow copies.
export function buildTree(locations) {
  const byId = {}
  for (const loc of locations) byId[loc.id] = { ...loc, children: [] }
  const roots = []
  for (const node of Object.values(byId)) {
    const parentId = node.parent?.id
    if (parentId && byId[parentId]) byId[parentId].children.push(node)
    else roots.push(node)
  }
  const sortRec = (nodes) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name))
    nodes.forEach((n) => sortRec(n.children))
  }
  sortRec(roots)
  return roots
}

// Full "Site › Room › Shelf" path for a location, resolved through the flat map.
export function pathString(loc, byId, sep = ' › ') {
  const names = []
  const seen = new Set()
  let cur = loc
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id)
    names.unshift(cur.name)
    cur = cur.parent?.id ? byId[cur.parent.id] : null
  }
  return names.join(sep)
}
