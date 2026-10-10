import React from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import { markdownPlugins } from './markdownPlugins'

export const MathView: React.FC<{
  content: string
  components: Components
  urlTransform: (url: string) => string
}> = ({ content, components, urlTransform }) => (
  <ReactMarkdown
    remarkPlugins={[...markdownPlugins, remarkMath]}
    rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: 'ignore' }]]}
    components={components}
    urlTransform={urlTransform}
  >
    {content}
  </ReactMarkdown>
)
