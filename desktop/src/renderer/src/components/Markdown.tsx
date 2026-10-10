import React, { lazy, Suspense, useMemo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import { workspaceHrefOf } from '../lib/fileKind'
import { markdownLinkRoute } from '../pages/knowledgeLinks'
import { useWorkspaceStore } from '../store/workspaceStore'
import { useLightboxStore } from './Lightbox'
import { CodeBlock } from './content/CodeBlock'
import { markdownPlugins } from './content/markdownPlugins'
import { resolveImageSrc } from './content/media'
import { safeUrl } from './content/url'

const MathView = lazy(() => import('./content/MathView').then((module) => ({ default: module.MathView })))

interface MarkdownProps {
  content: string
  /**
   * Intercept clicks on internal document links (relative `.md` hrefs). When
   * provided, such links open in-app instead of being handed to the OS. Used by
   * the knowledge viewer so index links open the target doc rather than firing
   * an "application cannot be opened (-120)" error in Electron.
   */
  onInternalLink?: (href: string) => void
  /**
   * Absolute directory of the document the markdown comes from, so image srcs
   * that are relative to it (`../images/x.png`) resolve to real files. Used by
   * the knowledge viewer; without it relative srcs are left untouched.
   */
  imageBaseDir?: string
}

const MarkdownContext = React.createContext<Pick<MarkdownProps, 'onInternalLink' | 'imageBaseDir'>>({})

function MarkdownLink({ href, children }: { href?: string; children?: React.ReactNode }) {
  const { onInternalLink } = React.useContext(MarkdownContext)
  const target = safeUrl(href || '')
  const route = markdownLinkRoute(href || '', Boolean(onInternalLink))
  if (route === 'knowledge' && onInternalLink) {
    return <a href={target} onClick={(event) => { event.preventDefault(); onInternalLink(target) }}>{children}</a>
  }
  const workspacePath = route === 'workspace' ? workspaceHrefOf(target) : null
  if (workspacePath) {
    return (
      <a href={target} data-ws-path={workspacePath} className="ws-link" onClick={(event) => {
        event.preventDefault()
        useWorkspaceStore.getState().openLink(workspacePath)
      }}>{children}</a>
    )
  }
  if (!target) return <span>{children}</span>
  return <a href={target} target="_blank" rel="noopener noreferrer">{children}</a>
}

function MarkdownImage({ src, alt }: { src?: string; alt?: string }) {
  const { imageBaseDir } = React.useContext(MarkdownContext)
  const resolved = resolveImageSrc(safeUrl(src || ''), imageBaseDir)
  if (!resolved) return null
  return (
    <img src={resolved} alt={alt || ''} onClick={() => useLightboxStore.getState().open(resolved)} />
  )
}

function MarkdownCode({ className, children }: { className?: string; children?: React.ReactNode }) {
  const raw = String(children ?? '')
  const block = Boolean(className?.includes('language-')) || raw.endsWith('\n')
  if (!block) return <code className={className}>{children}</code>
  const language = /language-([^\s]+)/.exec(className || '')?.[1] || 'text'
  return <CodeBlock language={language} code={raw.replace(/\n$/, '')} />
}

const components: Components = {
  a: MarkdownLink,
  img: MarkdownImage,
  pre: ({ children }) => <>{children}</>,
  code: MarkdownCode,
}

function hasMath(content: string): boolean {
  return /\$\$[\s\S]+?\$\$|\$[^$\n]+\$|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]/.test(content)
}

class MarkdownBoundary extends React.Component<{ source: string; children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true }
  }

  componentDidUpdate(previous: { source: string }): void {
    if (previous.source !== this.props.source && this.state.failed) this.setState({ failed: false })
  }

  render() {
    if (this.state.failed) {
      return <pre className="whitespace-pre-wrap break-words text-sm">{this.props.source}</pre>
    }
    return this.props.children
  }
}

function PlainMarkdown({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={markdownPlugins} components={components} urlTransform={safeUrl}>
      {content || ''}
    </ReactMarkdown>
  )
}

const Markdown: React.FC<MarkdownProps> = ({ content, onInternalLink, imageBaseDir }) => {
  const context = useMemo(() => ({ onInternalLink, imageBaseDir }), [onInternalLink, imageBaseDir])
  const source = content || ''
  const math = hasMath(source)
  return (
    <MarkdownContext.Provider value={context}>
      <div className="msg-content text-sm text-content leading-relaxed break-words">
        <MarkdownBoundary source={source}>
          {math ? (
            <Suspense fallback={<PlainMarkdown content={source} />}>
              <MathView content={source} components={components} urlTransform={safeUrl} />
            </Suspense>
          ) : <PlainMarkdown content={source} />}
        </MarkdownBoundary>
      </div>
    </MarkdownContext.Provider>
  )
}

export default Markdown
