"use client";

import { useEffect, useState, useCallback } from "react";
import { api, ApiError } from "@/lib/api-client";
import type { OntologyClass, OntologyEdge } from "@/types/curation";

interface ClassHierarchyProps {
  ontologyId: string;
  onClassSelect?: (classKey: string) => void;
}

interface TreeNode {
  cls: OntologyClass;
  children: TreeNode[];
}

function buildTree(
  classes: OntologyClass[],
  edges: OntologyEdge[],
): TreeNode[] {
  const childMap = new Map<string, string[]>();
  const hasParent = new Set<string>();

  for (const edge of edges) {
    const edgeType = (edge as Record<string, unknown>).edge_type ?? edge.type;
    if (edgeType !== "subclass_of") continue;
    const childKey = edge._from.split("/").pop() ?? edge._from;
    const parentKey = edge._to.split("/").pop() ?? edge._to;
    if (!childMap.has(parentKey)) childMap.set(parentKey, []);
    childMap.get(parentKey)!.push(childKey);
    hasParent.add(childKey);
  }

  const classMap = new Map(classes.map((c) => [c._key, c]));

  function createNode(key: string, visited: Set<string>): TreeNode | null {
    if (visited.has(key)) return null;
    const cls = classMap.get(key);
    if (!cls) return null;
    visited.add(key);

    const childKeys = childMap.get(key) ?? [];
    const children = childKeys
      .map((ck) => createNode(ck, visited))
      .filter((n): n is TreeNode => n !== null);

    return { cls, children };
  }

  const roots = classes.filter((c) => !hasParent.has(c._key));
  if (roots.length === 0 && classes.length > 0) {
    roots.push(classes[0]);
  }

  const visited = new Set<string>();
  const tree = roots
    .map((r) => createNode(r._key, visited))
    .filter((n): n is TreeNode => n !== null);

  for (const cls of classes) {
    if (!visited.has(cls._key)) {
      const node = createNode(cls._key, visited);
      if (node) tree.push(node);
    }
  }

  return tree;
}

function TreeItem({
  node,
  depth,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  onSelect?: (key: string) => void;
}) {
  const [expanded, setExpanded] = useState(depth < 2);
  const hasChildren = node.children.length > 0;

  return (
    <div data-testid={`tree-node-${node.cls._key}`}>
      <button
        onClick={() => {
          if (hasChildren) setExpanded(!expanded);
          onSelect?.(node.cls._key);
        }}
        className="flex items-center gap-1.5 w-full text-left px-2 py-1 rounded hover:bg-gray-100 transition-colors group"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {hasChildren ? (
          <span className="text-xs text-gray-400 w-4 flex-shrink-0">
            {expanded ? "\u25BC" : "\u25B6"}
          </span>
        ) : (
          <span className="w-4 flex-shrink-0" />
        )}
        <span className="text-sm text-gray-700 group-hover:text-gray-900 truncate">
          {node.cls.label}
        </span>
        <span className="ml-auto text-xs text-gray-400 flex-shrink-0">
          {((node.cls.confidence ?? 0) * 100).toFixed(0)}%
        </span>
      </button>

      {expanded &&
        hasChildren &&
        node.children.map((child) => (
          <TreeItem
            key={child.cls._key}
            node={child}
            depth={depth + 1}
            onSelect={onSelect}
          />
        ))}
    </div>
  );
}

export default function ClassHierarchy({
  ontologyId,
  onClassSelect,
}: ClassHierarchyProps) {
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [classRes, edgeRes] = await Promise.all([
        api.get<{ data: OntologyClass[] }>(
          `/api/v1/ontology/${ontologyId}/classes`,
        ),
        api.get<{ data: OntologyEdge[] }>(
          `/api/v1/ontology/${ontologyId}/edges`,
        ),
      ]);
      setTree(buildTree(classRes.data, edgeRes.data));
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : "Failed to load class hierarchy",
      );
    } finally {
      setLoading(false);
    }
  }, [ontologyId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const filterTree = useCallback(
    (nodes: TreeNode[], query: string): TreeNode[] => {
      if (!query) return nodes;
      const lower = query.toLowerCase();
      return nodes.reduce<TreeNode[]>((acc, node) => {
        const matchesSelf = node.cls.label.toLowerCase().includes(lower);
        const matchingChildren = filterTree(node.children, query);
        if (matchesSelf || matchingChildren.length > 0) {
          acc.push({
            ...node,
            children: matchesSelf ? node.children : matchingChildren,
          });
        }
        return acc;
      }, []);
    },
    [],
  );

  const displayTree = search ? filterTree(tree, search) : tree;

  return (
    <div className="space-y-3" data-testid="class-hierarchy">
      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search classes..."
        className="w-full text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        data-testid="hierarchy-search"
      />

      {loading && (
        <div className="py-6 text-center text-sm text-gray-400 animate-pulse" data-testid="hierarchy-loading">
          Loading class hierarchy...
        </div>
      )}

      {error && (
        <div className="py-3 px-3 text-sm text-red-600 bg-red-50 rounded-lg" data-testid="hierarchy-error">
          {error}
        </div>
      )}

      {!loading && !error && displayTree.length === 0 && (
        <div className="py-6 text-center text-sm text-gray-400" data-testid="hierarchy-empty">
          {search ? "No classes match your search." : "No classes found in this ontology."}
        </div>
      )}

      {!loading && displayTree.length > 0 && (
        <div className="max-h-[500px] overflow-y-auto">
          {displayTree.map((node) => (
            <TreeItem
              key={node.cls._key}
              node={node}
              depth={0}
              onSelect={onClassSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}
