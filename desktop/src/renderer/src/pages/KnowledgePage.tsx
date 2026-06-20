import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Loader2,
  Search,
  FileText,
  ChevronRight,
  ChevronDown,
  MessageSquarePlus,
  Network,
  Files,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { KnowledgeDir, KnowledgeFile, KnowledgeList, KnowledgeGraph as KnowledgeGraphData } from '../types'
import Markdown from '../components/Markdown'
import KnowledgeGraph from '../components/KnowledgeGraph'

interface KnowledgePageProps {
  baseUrl: string
}

type Tab = 'docs' | 'graph'

const formatSize = (bytes: number): string => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// Find the first document (root files first, then a DFS over the tree).
function firstFile(list: KnowledgeList): { path: string; title: string } | null {
  const root = list.root_files?.[0]
  if (root) return { path: root.name, title: root.title || root.name }
  const walk = (dir: KnowledgeDir, prefix: string): { path: string; title: string } | null => {
    const dirPath = prefix ? `${prefix}/${dir.dir}` : dir.dir
    const f = dir.files[0]
    if (f) return { path: `${dirPath}/${f.name}`, title: f.title || f.name }
    for (const c of dir.children) {
      const hit = walk(c, dirPath)
      if (hit) return hit
    }
    return null
  }
  for (const d of list.tree || []) {
    const hit = walk(d, '')
    if (hit) return hit
  }
  return null
}

const KnowledgePage: React.FC<KnowledgePageProps> = ({ baseUrl }) => {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('docs')
  const [data, setData] = useState<KnowledgeList | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  const [activePath, setActivePath] = useState<string | null>(null)
  const [docTitle, setDocTitle] = useState('')
  const [content, setContent] = useState('')
  const [docLoading, setDocLoading] = useState(false)

  const [graph, setGraph] = useState<KnowledgeGraphData | null>(null)
  const [graphLoading, setGraphLoading] = useState(false)

  const openDoc = useCallback(async (path: string, title: string) => {
    setActivePath(path)
    setDocTitle(title)
    setDocLoading(true)
    setContent('')
    try {
      const res = await apiClient.readKnowledge(path)
      setContent(res.content || '')
    } catch {
      setContent(`> ${t('knowledge_doc_load_error')}`)
    } finally {
      setDocLoading(false)
    }
  }, [])

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    let cancelled = false
    ;(async () => {
      try {
        setLoading(true)
        const fresh = await apiClient.getKnowledgeList()
        if (cancelled) return
        setData(fresh)
        // Auto-open the first document so the viewer isn't empty on entry.
        const first = firstFile(fresh)
        if (first) void openDoc(first.path, first.title)
      } catch (e) {
        console.error('Failed to load knowledge:', e)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [baseUrl, openDoc])

  const loadGraph = useCallback(async () => {
    if (graph) return
    setGraphLoading(true)
    try {
      setGraph(await apiClient.getKnowledgeGraph())
    } catch (e) {
      console.error('Failed to load graph:', e)
      setGraph({ nodes: [], links: [] })
    } finally {
      setGraphLoading(false)
    }
  }, [graph])

  const switchTab = (next: Tab) => {
    setTab(next)
    if (next === 'graph') void loadGraph()
  }

  // Jump from a graph node to its document.
  const onGraphSelect = useCallback(
    (id: string, label: string) => {
      setTab('docs')
      void openDoc(id, label)
    },
    [openDoc]
  )

  const totalPages = data?.stats?.pages ?? 0
  const statsLabel = useMemo(() => {
    if (!data) return ''
    return t('knowledge_stats')
      .replace('{pages}', String(data.stats?.pages ?? 0))
      .replace('{size}', formatSize(data.stats?.size ?? 0))
  }, [data])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-content-tertiary">
        <Loader2 size={18} className="animate-spin mr-2" />
        {t('knowledge_loading')}
      </div>
    )
  }

  const isEmpty = !data || totalPages === 0

  if (isEmpty) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
        <div className="w-14 h-14 rounded-2xl bg-accent-soft text-accent flex items-center justify-center mb-5">
          <Files size={26} />
        </div>
        <h2 className="text-lg font-semibold text-content mb-2">
          {data?.enabled === false ? t('knowledge_disabled') : t('knowledge_empty')}
        </h2>
        <p className="text-sm text-content-tertiary max-w-md mb-6">{t('knowledge_empty_guide')}</p>
        <button
          onClick={() => navigate('/')}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors"
        >
          <MessageSquarePlus size={15} />
          {t('knowledge_go_chat')}
        </button>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between px-6 pt-5 pb-3 flex-shrink-0">
        <div>
          <h2 className="text-xl font-bold text-content">{t('knowledge_title')}</h2>
          <p className="text-xs text-content-tertiary mt-1">{statsLabel}</p>
        </div>
        <div className="flex items-center gap-1 bg-inset rounded-btn p-0.5">
          <TabBtn icon={Files} label={t('knowledge_tab_docs')} active={tab === 'docs'} onClick={() => switchTab('docs')} />
          <TabBtn
            icon={Network}
            label={t('knowledge_tab_graph')}
            active={tab === 'graph'}
            onClick={() => switchTab('graph')}
          />
        </div>
      </div>

      {tab === 'docs' ? (
        <div className="flex-1 flex min-h-0 border-t border-default">
          {/* Tree sidebar */}
          <div className="w-72 flex-shrink-0 flex flex-col border-r border-default min-h-0">
            <div className="p-3 flex-shrink-0">
              <div className="relative">
                <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('knowledge_search')}
                  className="w-full pl-8 pr-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors"
                />
              </div>
            </div>
            <div className="flex-1 overflow-y-auto px-2 pb-3">
              <Tree
                data={data}
                search={search.trim().toLowerCase()}
                activePath={activePath}
                onOpen={openDoc}
              />
            </div>
          </div>

          {/* Document viewer */}
          <div className="flex-1 min-w-0 overflow-y-auto">
            {!activePath ? (
              <div className="h-full flex flex-col items-center justify-center text-content-tertiary">
                <FileText size={28} className="mb-3 opacity-50" />
                <p className="text-sm">{t('knowledge_select_hint')}</p>
              </div>
            ) : (
              <div className="max-w-3xl mx-auto px-6 py-6">
                <h1 className="text-lg font-semibold text-content mb-1">{docTitle}</h1>
                <p className="text-xs text-content-tertiary mb-5 font-mono">{activePath}</p>
                {docLoading ? (
                  <div className="flex items-center text-content-tertiary py-8">
                    <Loader2 size={16} className="animate-spin mr-2" />
                  </div>
                ) : (
                  <Markdown content={content} />
                )}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="flex-1 min-h-0 border-t border-default relative">
          {graphLoading ? (
            <div className="absolute inset-0 flex items-center justify-center text-content-tertiary">
              <Loader2 size={18} className="animate-spin mr-2" />
            </div>
          ) : graph && graph.nodes.length > 0 ? (
            <KnowledgeGraph data={graph} onSelect={onGraphSelect} />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-content-tertiary text-sm">
              {t('knowledge_graph_empty')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const TabBtn: React.FC<{
  icon: LucideIcon
  label: string
  active: boolean
  onClick: () => void
}> = ({ icon: Icon, label, active, onClick }) => (
  <button
    onClick={onClick}
    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[6px] text-sm font-medium cursor-pointer transition-colors ${
      active ? 'bg-surface text-content shadow-sm' : 'text-content-tertiary hover:text-content-secondary'
    }`}
  >
    <Icon size={14} />
    {label}
  </button>
)

// ---- Tree rendering --------------------------------------------------------

const Tree: React.FC<{
  data: KnowledgeList
  search: string
  activePath: string | null
  onOpen: (path: string, title: string) => void
}> = ({ data, search, activePath, onOpen }) => {
  const matches = (f: KnowledgeFile) => !search || f.title.toLowerCase().includes(search) || f.name.toLowerCase().includes(search)

  return (
    <div className="space-y-0.5">
      {(data.root_files || []).filter(matches).map((f) => (
        <FileLeaf
          key={f.name}
          path={f.name}
          title={f.title || f.name}
          active={activePath === f.name}
          onOpen={onOpen}
        />
      ))}
      {(data.tree || []).map((dir) => (
        <DirNode key={dir.dir} dir={dir} prefix="" search={search} activePath={activePath} onOpen={onOpen} />
      ))}
    </div>
  )
}

// Count files in a dir subtree that match the search.
function countMatches(dir: KnowledgeDir, search: string): number {
  const own = dir.files.filter(
    (f) => !search || f.title.toLowerCase().includes(search) || f.name.toLowerCase().includes(search)
  ).length
  return own + dir.children.reduce((acc, c) => acc + countMatches(c, search), 0)
}

const DirNode: React.FC<{
  dir: KnowledgeDir
  prefix: string
  search: string
  activePath: string | null
  onOpen: (path: string, title: string) => void
}> = ({ dir, prefix, search, activePath, onOpen }) => {
  const dirPath = prefix ? `${prefix}/${dir.dir}` : dir.dir
  const [open, setOpen] = useState(true)
  const matchCount = search ? countMatches(dir, search) : dir.files.length + dir.children.length
  if (search && matchCount === 0) return null

  const visibleFiles = dir.files.filter(
    (f) => !search || f.title.toLowerCase().includes(search) || f.name.toLowerCase().includes(search)
  )
  const expanded = open || !!search

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-1 px-2 py-1.5 rounded-btn text-sm text-content-secondary hover:bg-surface-2 cursor-pointer transition-colors"
      >
        {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <span className="truncate font-medium">{dir.dir}</span>
        <span className="ml-auto text-xs text-content-tertiary">{matchCount}</span>
      </button>
      {expanded && (
        <div className="ml-3 border-l border-default pl-1.5 space-y-0.5">
          {visibleFiles.map((f) => {
            const fpath = `${dirPath}/${f.name}`
            return (
              <FileLeaf
                key={fpath}
                path={fpath}
                title={f.title || f.name}
                active={activePath === fpath}
                onOpen={onOpen}
              />
            )
          })}
          {dir.children.map((c) => (
            <DirNode
              key={c.dir}
              dir={c}
              prefix={dirPath}
              search={search}
              activePath={activePath}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}
    </div>
  )
}

const FileLeaf: React.FC<{
  path: string
  title: string
  active: boolean
  onOpen: (path: string, title: string) => void
}> = ({ path, title, active, onOpen }) => (
  <button
    onClick={() => onOpen(path, title)}
    className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-btn text-sm cursor-pointer transition-colors text-left ${
      active ? 'bg-accent-soft text-accent' : 'text-content-secondary hover:bg-surface-2'
    }`}
  >
    <FileText size={13} className="flex-shrink-0 opacity-70" />
    <span className="truncate">{title}</span>
  </button>
)

export default KnowledgePage
