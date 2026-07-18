<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  node: { type: Object, required: true },
  depth: { type: Number, default: 0 },
})
const router = useRouter()
// Sites (depth 0) expand by default to reveal their rooms; deeper levels start
// collapsed so a big multi-site tree stays scannable.
const open = ref(props.depth < 1)
const hasChildren = () => props.node.children && props.node.children.length > 0
</script>

<template>
  <div class="tree-node">
    <div class="tree-row" :style="{ paddingLeft: depth * 20 + 8 + 'px' }">
      <button v-if="hasChildren()" class="tree-caret" :aria-expanded="open"
              :aria-label="open ? 'Collapse' : 'Expand'" @click="open = !open">
        {{ open ? '▾' : '▸' }}
      </button>
      <span v-else class="tree-caret-spacer"></span>

      <button class="tree-label" @click="router.push('/locations/' + node.id)">
        <span class="tree-name">📍 {{ node.name }}</span>
        <span class="tree-counts">
          <span v-if="node.itemCount" class="badge">{{ node.itemCount }} item{{ node.itemCount === 1 ? '' : 's' }}</span>
          <span v-if="node.bins?.length" class="badge">{{ node.bins.length }} bin{{ node.bins.length === 1 ? '' : 's' }}</span>
          <span v-if="hasChildren()" class="badge">{{ node.children.length }} sub</span>
        </span>
      </button>
    </div>

    <div v-if="open && hasChildren()">
      <LocationTreeNode v-for="c in node.children" :key="c.id" :node="c" :depth="depth + 1" />
    </div>
  </div>
</template>

<style scoped>
.tree-row {
  display: flex; align-items: center; gap: 6px;
  border-bottom: 1px solid var(--border);
}
.tree-caret, .tree-caret-spacer {
  width: 24px; height: 34px; flex-shrink: 0;
  display: grid; place-items: center;
  background: none; border: none; color: var(--muted);
  font-size: 0.8rem; padding: 0; cursor: pointer; border-radius: 6px;
}
.tree-caret:hover { background: var(--surface-2); color: var(--text); }
.tree-label {
  flex: 1; display: flex; align-items: center; gap: 10px; min-width: 0;
  background: none; border: none; color: var(--text);
  padding: 7px 8px; border-radius: 8px; cursor: pointer; text-align: left;
  font-weight: 500; font-size: 0.92rem;
}
.tree-label:hover { background: var(--accent-soft); }
.tree-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tree-counts { display: flex; gap: 5px; flex-shrink: 0; }
</style>
