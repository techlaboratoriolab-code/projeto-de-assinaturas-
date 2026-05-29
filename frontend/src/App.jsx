import { useState, useEffect, useRef, useCallback } from 'react'
import { ResponsiveContainer, ComposedChart, CartesianGrid, XAxis, YAxis, Tooltip, Bar, Line } from 'recharts'

const API = (import.meta.env.VITE_API_URL || `${window.location.protocol}//${window.location.host}`).replace(/\/$/, '')
const WS_APLIS_API = (import.meta.env.VITE_WS_APLIS_URL || `${window.location.protocol}//${window.location.host}/ws_aplis`).replace(/\/$/, '')
const MAX_LOG_LINES = 2000

// ── Design tokens ─────────────────────────────────────────────────────────────
const BG    = '#0b0d12'
const SURF  = '#111318'
const SURF2 = '#181c26'
const BDR   = 'rgba(255,255,255,0.07)'
const TX    = '#e2e8f0'
const TX2   = '#64748b'
const TX3   = '#374151'

// ── Hooks ─────────────────────────────────────────────────────────────────────
function useVisibleInterval(callback, delayMs) {
  useEffect(() => {
    const id = setInterval(() => { if (!document.hidden) callback() }, delayMs)
    return () => clearInterval(id)
  }, [callback, delayMs])
}

function useAplisStatus() {
  const [aplisData, setAplisData] = useState({})
  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${WS_APLIS_API}/api/requisicoes`)
      if (r.ok) setAplisData(await r.json())
    } catch {}
  }, [])
  useEffect(() => { refresh() }, [refresh])
  useVisibleInterval(refresh, 15000)
  return { aplisData, refresh }
}

async function chamarAnexa(requisicao) {
  console.info('[APLIS] anexar:start', { requisicao })
  const r = await fetch(`${API}/api/aplis/anexar/${encodeURIComponent(requisicao)}`, { method: 'POST' })
  const d = await r.json()
  console.info('[APLIS] anexar:response', { requisicao, httpStatus: r.status, body: d })
  return d
}

// ── Log helpers ───────────────────────────────────────────────────────────────
function classifyLine(line) {
  if (line.includes('[OK]'))       return 'ok'
  if (line.includes('[PENDENTE]')) return 'warn'
  if (line.includes('[ERRO]'))     return 'err'
  if (line.includes('[AVISO]'))    return 'warn'
  if (line.includes('[INFO]'))     return 'info'
  if (line.includes('[TESTE]'))    return 'test'
  if (line.startsWith('===') || line.startsWith('[BUSCA]') || line.startsWith('[RESUMO]')) return 'sep'
  return 'plain'
}
const lineColors = { ok: '#34d399', err: '#f87171', warn: '#fbbf24', info: '#60a5fa', test: '#a78bfa', sep: '#818cf8', plain: '#4b5563' }

// ── parseDashboard ────────────────────────────────────────────────────────────
function parseDashboard(lines) {
  const d = {
    totalGuias: null, comAss: null, semAss: null, enviados: null,
    iaAtual: 0, iaTotal: 0, dlAtual: 0, dlTotal: 0, wahaAtual: 0, wahaTotal: 0,
    etapa: null, guias: [], confirmacaoStatus: null,
    currentDownloadReq: null, currentDownloadNome: null,
    currentIaReq: null, currentIaMsg: null, currentWahaReq: null,
    fatalError: null, guiasNaoEncontradas: [],
  }
  const guiasMap = {}
  const ordemGuias = []
  const pushGuia = (cod, patch) => {
    if (!cod) return
    const key = String(cod)
    if (!guiasMap[key]) { guiasMap[key] = { cod: key, status: 'fila', msg: 'Aguardando analise' }; ordemGuias.push(key) }
    guiasMap[key] = { ...guiasMap[key], ...(patch || {}) }
  }
  for (const l of lines) {
    let m
    if (l.includes('Inicializando Vertex'))      d.etapa = 'init'
    if (l.includes('Buscando requisicoes'))      d.etapa = 'init'
    if (l.includes('Conectando a AWS S3'))       d.etapa = 'download'
    if (l.includes('Analisando') && l.includes('guias com Inteligencia')) d.etapa = 'ia'
    if (l.includes('RELATORIO DE ANALISE'))      d.etapa = 'relatorio'
    if (l.includes('Enviando mensagens de confirmacao')) d.etapa = 'waha'
    if (l.includes('Aguardando confirmac'))      d.etapa = 'aguardando'
    if (l.includes('ENVIO DE DOCUMENTOS'))       d.etapa = 'autentique'
    if (l.includes('documentos_autentique_producao')) d.etapa = 'done'
    if (l.includes('Modo apenas-log-motivos finalizado')) d.etapa = 'done'
    if (l.includes('Nenhuma requisicao encontrada no periodo especificado')) { d.etapa = 'done'; d.fatalError = 'Nenhuma requisicao encontrada no periodo especificado.' }
    if (l.includes('Nenhuma requisicao encontrada para o periodo informado')) { d.etapa = 'done'; d.fatalError = 'Nenhuma requisicao encontrada para o periodo informado.' }
    if ((m = l.match(/Encontradas:\s*(\d+)/i)))           d.totalGuias = +m[1]
    if ((m = l.match(/COM assinatura:\s*(\d+)/i)))        d.comAss = +m[1]
    if ((m = l.match(/SEM assinatura:\s*(\d+)/i)))        d.semAss = +m[1]
    if ((m = l.match(/Total de pacientes com telefone:\s*(\d+)/i))) d.wahaTotal = +m[1]
    if ((m = l.match(/^\s*\[(\d+)\/(\d+)\]\s+Conv.*Tipo\s+16/))) { d.dlAtual = +m[1]; d.dlTotal = +m[2] }
    if ((m = l.match(/^\s*\[(\d+)\/(\d+)\]\s+Conv\s+\S+\s+\|\s+Tipo\s+\S+\s+\|\s+(\S+)\s+\((.+)\)/))) {
      d.currentDownloadReq = m[3]; d.currentDownloadNome = m[4]
      pushGuia(m[3], { status: 'fila', msg: 'Aguardando analise' })
    }
    if ((m = l.match(/^\s*\[(\d+)\/(\d+)\]\s+Guia\s+(\S+):\s+(.+)/))) {
      d.iaAtual = +m[1]; d.iaTotal = +m[2]
      const cod = m[3]; const resto = m[4]
      d.currentIaReq = cod; d.currentIaMsg = resto
      let status = 'analisando'
      if (resto.includes('[OK]'))          status = 'ok'
      else if (resto.includes('[PENDENTE]')) status = 'pendente'
      else if (resto.includes('[AVISO]'))   status = 'aviso'
      if (/documento nao encontrado/i.test(resto)) d.guiasNaoEncontradas.push(cod)
      pushGuia(cod, { status, msg: resto.replace(/\[.*?\]\s*/, '').trim() })
    }
    if ((m = l.match(/^\[(\d+)\/(\d+)\]\s+Req.*Conv/))) { d.wahaAtual = +m[1]; d.wahaTotal = Math.max(d.wahaTotal || 0, +m[2]) }
    if ((m = l.match(/^\[(\d+)\/(\d+)\]\s+Req\s+(\S+)/))) d.currentWahaReq = m[3]
    if (l.includes('Aguardando resposta do paciente') || l.includes('Aguardando resposta de')) d.confirmacaoStatus = 'aguardando'
    if (l.includes('Confirmação recebida')) d.confirmacaoStatus = 'confirmado'
    if (l.includes('Negativa recebida') || l.includes('NAO confirmou')) d.confirmacaoStatus = 'negado'
    if ((m = l.match(/Documento enviado! ID:/))) d.enviados = (d.enviados || 0) + 1
  }
  d.guias = ordemGuias.map(c => guiasMap[c]).filter(Boolean)
  return d
}

function formatDateLocal(d) {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
}
function fmtDate(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return d.toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit' })
}

const STEPS = [
  { id:'init',       label:'Buscando guias' },
  { id:'download',   label:'Download' },
  { id:'ia',         label:'Análise IA' },
  { id:'relatorio',  label:'Relatório' },
  { id:'waha',       label:'WhatsApp' },
  { id:'aguardando', label:'Confirmação' },
  { id:'autentique', label:'Autentique' },
  { id:'done',       label:'Concluído' },
]
const STEP_ORDER = STEPS.map(s => s.id)

function getEtapaResumo(d, running, done) {
  const etapa = d.etapa || (done ? 'done' : 'init')
  if (!running && d.fatalError) return { titulo: 'Nenhuma guia encontrada no período', detalhe: d.fatalError + ' Ajuste o período e tente novamente.' }
  if (etapa === 'download')   return { titulo: 'Baixando documentos', detalhe: `${d.dlAtual || 0} de ${d.dlTotal || 0} documentos baixados.` }
  if (etapa === 'ia')         return { titulo: 'Analisando assinaturas com IA', detalhe: `${d.iaAtual || 0} de ${d.iaTotal || 0} guias analisadas.` }
  if (etapa === 'relatorio')  return { titulo: 'Consolidando relatório', detalhe: 'Fechando totais de assinatura e pendências.' }
  if (etapa === 'waha')       return { titulo: 'Enviando mensagens no WhatsApp', detalhe: `${d.wahaAtual || 0} de ${d.wahaTotal || 0} contatos processados.` }
  if (etapa === 'aguardando') return { titulo: 'Aguardando resposta dos pacientes', detalhe: 'Esperando confirmação para envio do documento.' }
  if (etapa === 'autentique') return { titulo: 'Enviando documentos para assinatura', detalhe: `${d.enviados || 0} documento(s) enviado(s).` }
  if (etapa === 'done')       return { titulo: 'Processo concluído', detalhe: 'Resultados disponíveis no painel.' }
  if (running)                return { titulo: 'Preparando processamento', detalhe: 'Iniciando conexões e buscando guias.' }
  return { titulo: 'Aguardando nova execução', detalhe: 'Clique em Iniciar processamento para rodar uma nova análise.' }
}

function buildChartData(records) {
  const rows = Array.isArray(records) ? [...records].reverse() : []
  return rows.slice(-14).map(r => {
    const dt = r?.started_at ? new Date(r.started_at) : null
    const label = dt && !Number.isNaN(dt.getTime())
      ? `${String(dt.getDate()).padStart(2,'0')}/${String(dt.getMonth()+1).padStart(2,'0')}` : '—'
    const enviados = Number(r?.enviados || 0)
    const alvo     = Number(r?.total_alvo || 0)
    const taxa     = alvo > 0 ? Math.round((enviados / alvo) * 100) : null
    return { dia: label, enviados, alvo, taxa }
  })
}

// ── Primitivos visuais ────────────────────────────────────────────────────────
function Toggle({ checked, onChange, disabled }) {
  return (
    <button onClick={() => !disabled && onChange(!checked)} disabled={disabled} style={{
      width: 36, height: 20, borderRadius: 99, border: 'none', flexShrink: 0,
      background: checked ? '#3b82f6' : 'rgba(255,255,255,0.1)',
      cursor: disabled ? 'not-allowed' : 'pointer',
      position: 'relative', transition: 'background .15s', opacity: disabled ? .4 : 1,
    }}>
      <span style={{
        position: 'absolute', top: 2, left: checked ? 18 : 2, width: 16, height: 16,
        borderRadius: '50%', background: '#fff', transition: 'left .15s',
        boxShadow: '0 1px 3px rgba(0,0,0,.5)',
      }} />
    </button>
  )
}

function Badge({ color, children }) {
  const map = {
    green:  { bg: 'rgba(52,211,153,0.1)',  fg: '#34d399', bdr: 'rgba(52,211,153,0.2)'  },
    yellow: { bg: 'rgba(251,191,36,0.1)',  fg: '#fbbf24', bdr: 'rgba(251,191,36,0.2)'  },
    red:    { bg: 'rgba(248,113,113,0.1)', fg: '#f87171', bdr: 'rgba(248,113,113,0.2)' },
    blue:   { bg: 'rgba(96,165,250,0.1)',  fg: '#60a5fa', bdr: 'rgba(96,165,250,0.2)'  },
    purple: { bg: 'rgba(167,139,250,0.1)', fg: '#a78bfa', bdr: 'rgba(167,139,250,0.2)' },
    gray:   { bg: 'rgba(255,255,255,0.05)',fg: TX2,       bdr: BDR                      },
  }
  const s = map[color] || map.gray
  return (
    <span style={{ background: s.bg, color: s.fg, border: `0.5px solid ${s.bdr}`, borderRadius: 99, fontSize: 11, padding: '2px 8px', whiteSpace: 'nowrap', display: 'inline-block' }}>
      {children}
    </span>
  )
}

function Pill({ label, active, onClick }) {
  return (
    <button onClick={onClick} style={{
      padding: '5px 14px', fontSize: 12.5, fontWeight: active ? 500 : 400,
      cursor: 'pointer', border: 'none', borderRadius: 7, transition: 'all .13s',
      background: active ? 'rgba(255,255,255,0.09)' : 'transparent',
      color: active ? TX : TX2, fontFamily: 'inherit',
      boxShadow: active ? `inset 0 0 0 0.5px ${BDR}` : 'none',
    }}>
      {label}
    </button>
  )
}

function Btn({ children, onClick, variant = 'ghost', disabled, title, style: extraStyle }) {
  const base = { display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'inherit', borderRadius: 7, fontSize: 12, fontWeight: 400, cursor: disabled ? 'not-allowed' : 'pointer', border: 'none', transition: 'all .13s', whiteSpace: 'nowrap', padding: '7px 13px', opacity: disabled ? .45 : 1, ...extraStyle }
  const v = {
    primary: { background: '#2563eb', color: '#fff', fontWeight: 500 },
    danger:  { background: 'rgba(248,113,113,0.1)', color: '#fca5a5', border: `0.5px solid rgba(248,113,113,0.25)` },
    ghost:   { background: 'rgba(255,255,255,0.05)', color: TX2, border: `0.5px solid ${BDR}` },
    quiet:   { background: 'transparent', color: TX3, border: 'none' },
  }
  return (
    <button onClick={!disabled ? onClick : undefined} title={title} disabled={disabled} style={{ ...base, ...v[variant] }}>
      {children}
    </button>
  )
}

function Input({ value, onChange, placeholder, style: extra, type = 'text', disabled }) {
  return (
    <input
      type={type} value={value} onChange={onChange} placeholder={placeholder}
      disabled={disabled}
      style={{
        background: SURF2, border: `0.5px solid ${BDR}`, borderRadius: 7,
        color: TX, padding: '7px 12px', fontSize: 12.5, fontFamily: 'inherit',
        outline: 'none', colorScheme: 'dark', ...extra,
      }}
    />
  )
}

function Divider() {
  return <div style={{ height: '0.5px', background: BDR, margin: '0 -20px' }} />
}

function SectionLabel({ children }) {
  return <div style={{ fontSize: 10, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '.08em', color: TX3 }}>{children}</div>
}

function ExecStatusBadge({ status }) {
  const s = String(status || '').toLowerCase()
  if (s === 'concluido')    return <Badge color="green">Concluído</Badge>
  if (s === 'cancelado')    return <Badge color="red">Cancelado</Badge>
  if (s === 'interrompido') return <Badge color="yellow">Interrompido</Badge>
  if (s === 'sem_dados')    return <Badge color="yellow">Sem guias</Badge>
  if (s === 'erro')         return <Badge color="red">Falhou</Badge>
  return <Badge color="gray">—</Badge>
}

function fmtExecDuration(startedAt, finishedAt) {
  if (!startedAt || !finishedAt) return '—'
  const diffMs = new Date(finishedAt) - new Date(startedAt)
  if (!Number.isFinite(diffMs) || diffMs < 0) return '—'
  const diffSec = Math.round(diffMs / 1000)
  if (diffSec < 60) return `${diffSec}s`
  const diffMin = Math.round(diffSec / 60)
  return `${diffMin}min`
}

function AplisStatusBadge({ status }) {
  if (status === 'assinado') return <Badge color="green">Guia Anexada</Badge>
  if (status === 'pendente') return <Badge color="yellow">Aguardando Assinatura</Badge>
  if (status === 'erro')     return <Badge color="red">Falha no Anexo</Badge>
  return null
}

function TrendArrow({ value }) {
  const n = Number(value || 0)
  const color = n > 0 ? '#34d399' : n < 0 ? '#f87171' : TX2
  return <span style={{ color, fontSize: 20, fontWeight: 400 }}>{n > 0 ? `+${n}` : `${n}`}</span>
}

// ── Gráfico de histórico ──────────────────────────────────────────────────────
function HistoryChart({ records }) {
  const data = buildChartData(records)
  if (!data.length) return <div style={{ color: TX3, fontSize: 12, textAlign: 'center', padding: '32px 0' }}>Sem histórico disponível.</div>
  const hasRight = data.some(d => d.taxa !== null)
  return (
    <div style={{ width: '100%', height: 160 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 4, right: hasRight ? 38 : 4, left: -22, bottom: 0 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.035)" vertical={false} />
          <XAxis dataKey="dia" stroke="transparent" tick={{ fill: TX3, fontSize: 9.5 }} axisLine={false} tickLine={false} />
          <YAxis yAxisId="l" stroke="transparent" tick={{ fill: TX3, fontSize: 9.5 }} axisLine={false} tickLine={false} allowDecimals={false} />
          {hasRight && (
            <YAxis yAxisId="r" orientation="right" stroke="transparent" tick={{ fill: TX3, fontSize: 9.5 }} axisLine={false} tickLine={false} domain={[0, 100]} tickCount={3} tickFormatter={v => `${v}%`} />
          )}
          <Tooltip
            contentStyle={{ background: '#0d1117', border: `0.5px solid rgba(255,255,255,0.1)`, borderRadius: 8, fontSize: 11.5, fontFamily: 'inherit', boxShadow: '0 8px 24px rgba(0,0,0,.5)' }}
            labelStyle={{ color: TX2, marginBottom: 4, fontWeight: 500 }}
            itemStyle={{ color: TX }}
            cursor={{ fill: 'rgba(255,255,255,0.025)' }}
          />
          <Bar yAxisId="l" dataKey="alvo" name="Alvo" fill="rgba(100,116,139,0.2)" radius={[3,3,0,0]} maxBarSize={22} />
          <Bar yAxisId="l" dataKey="enviados" name="Enviados" fill="#3b82f6" fillOpacity={0.85} radius={[3,3,0,0]} maxBarSize={22} />
          {hasRight && (
            <Line yAxisId="r" type="monotone" dataKey="taxa" name="Taxa" stroke="#34d399" strokeWidth={1.5} dot={{ r: 2.5, fill: '#34d399', strokeWidth: 0 }} connectNulls />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Progress bar ──────────────────────────────────────────────────────────────
function ProgressBar({ atual, total, color = '#3b82f6', animate = false }) {
  const pct = total > 0 ? Math.round((atual / total) * 100) : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ flex: 1, height: 3, background: 'rgba(255,255,255,0.07)', borderRadius: 99, overflow: 'hidden' }}>
        {animate
          ? <div style={{ height: '100%', width: '30%', borderRadius: 99, background: color, animation: 'bar-slide 1.6s ease-in-out infinite' }} />
          : <div style={{ height: '100%', width: `${pct}%`, borderRadius: 99, background: color, transition: 'width .4s ease' }} />
        }
      </div>
      {!animate && <span style={{ fontSize: 11, color: TX2, minWidth: 30, textAlign: 'right' }}>{pct}%</span>}
    </div>
  )
}

// ── Step bar ──────────────────────────────────────────────────────────────────
function StepBar({ etapa }) {
  const curIdx = STEP_ORDER.indexOf(etapa ?? 'init')
  return (
    <div style={{ display: 'flex', alignItems: 'center', overflowX: 'auto', gap: 0, paddingBottom: 2 }}>
      {STEPS.map((step, i) => {
        const done   = curIdx > i
        const active = curIdx === i
        return (
          <div key={step.id} style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, padding: '6px 10px', borderRadius: 8, background: active ? 'rgba(59,130,246,0.1)' : 'transparent', border: `0.5px solid ${active ? 'rgba(59,130,246,0.3)' : 'transparent'}` }}>
              <div style={{ width: 22, height: 22, borderRadius: '50%', display: 'grid', placeItems: 'center', fontSize: 10, fontWeight: 500, background: done ? 'rgba(52,211,153,0.15)' : active ? 'rgba(59,130,246,0.2)' : 'rgba(255,255,255,0.05)', color: done ? '#34d399' : active ? '#60a5fa' : TX3, border: `0.5px solid ${done ? 'rgba(52,211,153,0.25)' : active ? 'rgba(59,130,246,0.35)' : BDR}` }}>
                {done ? '✓' : i + 1}
              </div>
              <span style={{ fontSize: 9.5, color: done ? '#34d399' : active ? '#60a5fa' : TX3, whiteSpace: 'nowrap', fontWeight: active ? 500 : 400 }}>{step.label}</span>
            </div>
            {i < STEPS.length - 1 && <div style={{ width: 16, height: 1, background: done ? 'rgba(52,211,153,0.3)' : 'rgba(255,255,255,0.06)', flexShrink: 0 }} />}
          </div>
        )
      })}
    </div>
  )
}

// ── Guias grid ────────────────────────────────────────────────────────────────
const guiaStatus = {
  ok:        { color: '#34d399', label: 'Assinada' },
  pendente:  { color: '#fbbf24', label: 'Sem assinatura' },
  aviso:     { color: '#fb923c', label: 'Não encontrada' },
  fila:      { color: '#60a5fa', label: 'Na fila' },
  analisando:{ color: '#a78bfa', label: 'Analisando…' },
}

function GuiasGrid({ guias, iaTotal, onEnviarIndividual, enviandoReq, running }) {
  const [limit, setLimit] = useState(24)
  useEffect(() => { setLimit(24) }, [iaTotal])
  if (!guias.length) return null
  const exibidas = guias.slice(0, limit)
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <SectionLabel>Resultado por guia</SectionLabel>
        <span style={{ fontSize: 11, color: TX3 }}>{Math.min(exibidas.length, guias.length)} de {Math.max(guias.length, iaTotal || 0)}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 4 }}>
        {exibidas.map(g => {
          const s = guiaStatus[g.status] || { color: TX3, label: 'Indefinido' }
          const isPendente = g.status === 'pendente'
          const isEnviando = enviandoReq === g.cod
          return (
            <div key={g.cod} style={{ background: SURF2, border: `0.5px solid ${BDR}`, borderRadius: 7, padding: '8px 10px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: isPendente && onEnviarIndividual ? 82 : 62 }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ fontFamily: 'monospace', fontSize: 10.5, color: '#818cf8' }}>{g.cod}</span>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: s.color, flexShrink: 0 }} />
                </div>
                <span style={{ fontSize: 10, color: s.color }}>{s.label}</span>
              </div>
              {isPendente && onEnviarIndividual && (
                <div style={{ marginTop: 8 }}>
                  <button
                    onClick={(e) => { e.stopPropagation(); onEnviarIndividual(g.cod) }}
                    disabled={running || !!enviandoReq}
                    style={{
                      width: '100%',
                      background: '#2563eb',
                      color: '#fff',
                      border: 'none',
                      borderRadius: 4,
                      padding: '3px 6px',
                      fontSize: 9,
                      fontWeight: 500,
                      cursor: (running || enviandoReq) ? 'not-allowed' : 'pointer',
                      opacity: (running || enviandoReq) ? 0.6 : 1,
                      transition: 'all 0.1s',
                      textAlign: 'center'
                    }}
                  >
                    {isEnviando ? 'Enviando…' : 'Enviar assinatura'}
                  </button>
                </div>
              )}
            </div>
          )
        })}
      </div>
      {guias.length > limit && (
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: 10 }}>
          <Btn onClick={() => setLimit(v => Math.min(guias.length, v + 24))}>Carregar mais</Btn>
        </div>
      )}
    </div>
  )
}

// ── Dashboard (progresso em tempo real) ──────────────────────────────────────
function Dashboard({ running, logs, done, executionSnapshot, onEnviarIndividual, enviandoReq }) {
  const d = parseDashboard(logs)
  const snap = executionSnapshot || {}
  if (running && snap?.running) {
    if (snap.etapa) d.etapa = snap.etapa
    if (Number.isFinite(snap.download_atual)) d.dlAtual = snap.download_atual
    if (Number.isFinite(snap.download_total)) d.dlTotal = snap.download_total
    if (Number.isFinite(snap.ia_atual))       d.iaAtual = snap.ia_atual
    if (Number.isFinite(snap.ia_total))       d.iaTotal = snap.ia_total
    if (Number.isFinite(snap.waha_atual))     d.wahaAtual = snap.waha_atual
    if (Number.isFinite(snap.waha_total))     d.wahaTotal = snap.waha_total
    if (snap.current_requisicao)              d.currentIaReq = snap.current_requisicao
    if (snap.last_line && !d.currentIaMsg)   d.currentIaMsg = snap.last_line
  }
  if (Number.isFinite(snap.enviados) && snap.enviados > 0) d.enviados = Math.max(d.enviados || 0, snap.enviados)
  if (!running && !logs.length) return null

  const etapaResumo   = getEtapaResumo(d, running, done)
  const comAssParcial = d.comAss ?? d.guias.filter(g => g.status === 'ok').length
  const semAssParcial = d.semAss ?? d.guias.filter(g => g.status === 'pendente').length
  const totalParcial  = d.totalGuias ?? d.dlTotal ?? d.iaTotal
  const naoEnc        = d.guiasNaoEncontradas.length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {/* Stepper */}
      <Card pad>
        <StepBar etapa={d.etapa} />
      </Card>

      {/* Etapa atual */}
      <Card pad>
        <SectionLabel>Etapa atual</SectionLabel>
        <div style={{ marginTop: 8, fontSize: 15, fontWeight: 500, color: TX }}>{etapaResumo.titulo}</div>
        <div style={{ marginTop: 4, fontSize: 12, color: TX2, lineHeight: 1.55 }}>{etapaResumo.detalhe}</div>
      </Card>

      {/* Métricas */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px,1fr))', gap: 6 }}>
        {[
          { label: 'Guias encontradas', value: totalParcial,  color: TX },
          { label: 'Com assinatura',    value: comAssParcial, color: '#34d399' },
          { label: 'Sem assinatura',    value: semAssParcial, color: '#fbbf24' },
          { label: 'Não encontradas',   value: naoEnc,        color: '#fb923c' },
          { label: 'Docs enviados',     value: d.enviados,    color: '#60a5fa' },
        ].map(c => (
          <Card pad key={c.label}>
            <SectionLabel>{c.label}</SectionLabel>
            <div style={{ fontSize: 26, fontWeight: 400, color: c.value != null ? c.color : TX3, marginTop: 8, lineHeight: 1 }}>{c.value ?? '—'}</div>
          </Card>
        ))}
      </div>

      {/* Barras de progresso */}
      {(d.dlTotal > 0 || d.iaTotal > 0 || d.wahaTotal > 0 || d.confirmacaoStatus || (d.enviados != null && d.semAss != null)) && (
        <Card pad>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {d.dlTotal > 0 && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: TX2 }}>Download de documentos</span>
                  <span style={{ fontSize: 11, color: TX3 }}>{d.dlAtual}/{d.dlTotal}</span>
                </div>
                <ProgressBar atual={d.dlAtual} total={d.dlTotal} color="#60a5fa" />
              </div>
            )}
            {d.iaTotal > 0 && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: TX2 }}>Análise por IA</span>
                  <span style={{ fontSize: 11, color: TX3 }}>{d.iaAtual}/{d.iaTotal}</span>
                </div>
                <ProgressBar atual={d.iaAtual} total={d.iaTotal} color="#a78bfa" />
              </div>
            )}
            {d.wahaTotal > 0 && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: TX2 }}>Mensagens WhatsApp</span>
                  <span style={{ fontSize: 11, color: TX3 }}>{d.wahaAtual}/{d.wahaTotal}</span>
                </div>
                <ProgressBar atual={d.wahaAtual} total={d.wahaTotal} color="#34d399" />
              </div>
            )}
            {d.confirmacaoStatus && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: 12, color: TX2 }}>Confirmação dos pacientes</span>
                  {d.confirmacaoStatus === 'aguardando' && <Badge color="yellow">Aguardando</Badge>}
                  {d.confirmacaoStatus === 'confirmado' && <Badge color="green">Confirmado</Badge>}
                  {d.confirmacaoStatus === 'negado'     && <Badge color="red">Recusado</Badge>}
                </div>
                <ProgressBar atual={1} total={1} color={d.confirmacaoStatus === 'confirmado' ? '#34d399' : d.confirmacaoStatus === 'negado' ? '#f87171' : '#fbbf24'} animate={d.confirmacaoStatus === 'aguardando'} />
              </div>
            )}
            {d.enviados != null && d.semAss != null && (
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontSize: 12, color: TX2 }}>Documentos enviados para assinatura</span>
                  <span style={{ fontSize: 11, color: TX3 }}>{d.enviados}/{d.semAss}</span>
                </div>
                <ProgressBar atual={d.enviados} total={d.semAss} color="#3b82f6" />
              </div>
            )}
          </div>
        </Card>
      )}

      {naoEnc > 0 && (
        <div style={{ background: 'rgba(251,146,60,0.07)', border: '0.5px solid rgba(251,146,60,0.2)', borderRadius: 10, padding: '12px 16px' }}>
          <div style={{ fontSize: 12, color: '#fb923c', marginBottom: 8 }}>
            {naoEnc} guia(s) não encontrada(s) no storage
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {d.guiasNaoEncontradas.slice(0, 40).map(cod => (
              <span key={cod} style={{ background: SURF2, border: `0.5px solid ${BDR}`, borderRadius: 4, padding: '2px 7px', color: TX2, fontSize: 10.5, fontFamily: 'monospace' }}>{cod}</span>
            ))}
            {naoEnc > 40 && <span style={{ color: TX3, fontSize: 11 }}>+{naoEnc - 40} mais</span>}
          </div>
        </div>
      )}

      {d.guias.length > 0 && (
        <Card pad>
          <GuiasGrid guias={d.guias} iaTotal={d.iaTotal} onEnviarIndividual={onEnviarIndividual} enviandoReq={enviandoReq} running={running} />
        </Card>
      )}
    </div>
  )
}

// ── Card wrapper ──────────────────────────────────────────────────────────────
function Card({ children, pad, style: extra }) {
  return (
    <div style={{ background: SURF, border: `0.5px solid ${BDR}`, borderRadius: 10, ...(pad ? { padding: '16px 20px' } : {}), ...extra }}>
      {children}
    </div>
  )
}

// ── Tabela genérica helper ────────────────────────────────────────────────────
const TH = { padding: '9px 16px', color: TX3, fontSize: 10, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '.08em', textAlign: 'left', whiteSpace: 'nowrap', borderBottom: `0.5px solid ${BDR}` }
const TD = { padding: '10px 16px', fontSize: 12.5, color: '#cbd5e1', borderBottom: `0.5px solid rgba(255,255,255,0.04)`, verticalAlign: 'middle' }

function TRow({ children, onClick }) {
  const [hover, setHover] = useState(false)
  return (
    <tr
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{ background: hover ? 'rgba(255,255,255,0.02)' : 'transparent', transition: 'background .1s', cursor: onClick ? 'pointer' : 'default' }}
    >
      {children}
    </tr>
  )
}

// ── Log viewer ────────────────────────────────────────────────────────────────
function LogViewer({ logs, totalLines, running, pinned, onScroll, onScrollToBottom, onClear }) {
  const logRef = useRef(null)
  const pinnedR = useRef(pinned)
  useEffect(() => { pinnedR.current = pinned }, [pinned])
  useEffect(() => { if (pinnedR.current && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight }, [logs])
  return (
    <div style={{ background: '#06080d', border: `0.5px solid ${BDR}`, borderRadius: 10, display: 'flex', flexDirection: 'column', height: 200 }}>
      <div style={{ padding: '8px 14px', borderBottom: `0.5px solid ${BDR}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <SectionLabel>Log detalhado</SectionLabel>
          {running && <Badge color="purple">ao vivo</Badge>}
          {totalLines > 0 && <span style={{ color: TX3, fontSize: 10 }}>{totalLines} linhas</span>}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {!pinned && <Btn onClick={onScrollToBottom} style={{ animation: 'pulse-d 1.5s infinite', fontSize: 11, padding: '3px 10px' }}>↓ Seguir</Btn>}
          <Btn onClick={onClear} style={{ fontSize: 11, padding: '3px 10px' }}>Limpar</Btn>
        </div>
      </div>
      <div ref={logRef} onScroll={onScroll} style={{ flex: 1, overflowY: 'auto', padding: '8px 14px', fontFamily: "'Cascadia Code','Fira Code','Consolas',monospace", fontSize: 10.5, lineHeight: 1.7 }}>
        {logs.length === 0
          ? <div style={{ color: TX3, fontStyle: 'italic' }}>{running ? 'Aguardando saída…' : 'Nenhuma execução ainda.'}</div>
          : logs.map((line, i) => <div key={i} style={{ color: lineColors[classifyLine(line)], whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{line}</div>)
        }
      </div>
    </div>
  )
}

// ── Aba Documentos Autentique ──────────────────────────────────────────────────
function AbaDocumentos() {
  const [docs, setDocs]               = useState([])
  const [total, setTotal]             = useState(null)
  const [page, setPage]               = useState(1)
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState(null)
  const [aplisMsg, setAplisMsg]       = useState(null)
  const [aplisLocal, setAplisLocal]   = useState({})
  const [busca, setBusca]             = useState('')
  const { aplisData, refresh: refA }  = useAplisStatus()
  const [anexandoReq, setAnexandoReq] = useState('')
  const [previewReq, setPreviewReq]   = useState('')
  const [previewItems, setPreviewItems]   = useState([])
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError]     = useState(null)
  const [previewSel, setPreviewSel]         = useState(null)
  const LIMIT = 20

  const fetchDocs = useCallback(async (p) => {
    setLoading(true); setError(null)
    try {
      const r = await fetch(`${API}/api/autentique/documentos?page=${p}&limit=${LIMIT}`)
      const d = await r.json()
      if (d.error) { setError(d.error); return }
      setDocs(d.docs); setTotal(d.total)
    } catch { setError('Falha ao buscar documentos') }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchDocs(page) }, [page, fetchDocs])

  const abrirImagens = useCallback(async (req) => {
    setPreviewReq(req); setPreviewItems([]); setPreviewError(null); setPreviewSel(null); setPreviewLoading(true)
    try {
      const r = await fetch(`${API}/api/requisicoes/${encodeURIComponent(req)}/imagens`)
      const d = await r.json()
      if (d.error) { setPreviewError(d.error); return }
      setPreviewItems(d.items || [])
      if ((d.items || []).length) setPreviewSel(d.items[0])
      if (!(d.items || []).length) setPreviewError('Nenhuma imagem encontrada para essa requisição.')
    } catch { setPreviewError('Falha ao carregar imagens.') }
    finally { setPreviewLoading(false) }
  }, [])

  const anexar = useCallback(async (req) => {
    setError(null)
    setAplisMsg(null)
    setAnexandoReq(req)
    try {
      const d = await chamarAnexa(req)
      if (!d.sucesso) {
        setAplisLocal(prev => ({ ...prev, [req]: 'erro' }))
        setError(d.erro || 'Falha ao anexar guia no APLIS')
      } else {
        setAplisLocal(prev => ({ ...prev, [req]: 'assinado' }))
        const meta = d.anexo_aplis
        const sufixo = meta
          ? ` (idImagem ${meta.idRequisicaoImagem}, tipo ${meta.tipo}, arquivo ${meta.arquivo}.${String(meta.extensao || '').toLowerCase()})`
          : ''
        setAplisMsg(d.ja_anexado
          ? `Requisição ${req}: guia já estava anexada no APLIS.${sufixo}`
          : `Requisição ${req}: guia anexada com sucesso no APLIS.${sufixo}`)
      }
      refA()
    } catch { setError('Erro ao conectar ao WS APLIS') }
    setAnexandoReq('')
  }, [refA])

  const totalPages = total != null ? Math.ceil(total / LIMIT) : 1
  const filtered = busca.trim()
    ? docs.filter(d => d.requisicao.includes(busca) || d.nome.toLowerCase().includes(busca.toLowerCase()) || (d.email || '').toLowerCase().includes(busca.toLowerCase()))
    : docs

  function DocBadge({ doc }) {
    if (doc.rejeitado)   return <Badge color="red">Rejeitado</Badge>
    if (doc.assinado)    return <Badge color="green">Assinado</Badge>
    if (doc.visualizado) return <Badge color="yellow">Visualizado</Badge>
    return <Badge color="gray">Pendente</Badge>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <Input value={busca} onChange={e => setBusca(e.target.value)} placeholder="Buscar por requisição, nome ou e-mail…" style={{ width: 320 }} />
        {total != null && <span style={{ color: TX3, fontSize: 12 }}>{total} documentos</span>}
        <div style={{ flex: 1 }} />
        <Btn onClick={() => fetchDocs(page)}>↻ Atualizar</Btn>
      </div>
      {error && <div style={{ color: '#f87171', fontSize: 12 }}>{error}</div>}
      {aplisMsg && <div style={{ color: '#34d399', fontSize: 12 }}>{aplisMsg}</div>}

      {/* Tabela */}
      <Card>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                {['Requisição', 'Paciente', 'Contato', 'Status', 'Enviado em', 'Assinado em', 'Link', 'Guia APLIS'].map(h => <th key={h} style={TH}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {loading
                ? <tr><td colSpan={8} style={{ ...TD, textAlign: 'center', color: TX3, padding: 40 }}>Carregando…</td></tr>
                : filtered.length === 0
                ? <tr><td colSpan={8} style={{ ...TD, textAlign: 'center', color: TX3, padding: 40 }}>Nenhum documento encontrado.</td></tr>
                : filtered.map(doc => (
                  <TRow key={doc.id}>
                    <td style={{ ...TD, fontFamily: 'monospace', color: '#818cf8' }}>
                      <button onClick={() => abrirImagens(doc.requisicao)} style={{ background: 'none', border: 'none', color: '#818cf8', cursor: 'pointer', fontFamily: 'monospace', fontSize: 12.5, padding: 0 }}>{doc.requisicao}</button>
                    </td>
                    <td style={TD}>{doc.nome}</td>
                    <td style={{ ...TD, color: TX2, fontSize: 11.5 }}>{doc.email}</td>
                    <td style={TD}><DocBadge doc={doc} /></td>
                    <td style={{ ...TD, color: TX2, fontSize: 11.5 }}>{fmtDate(doc.criado_em) || '—'}</td>
                    <td style={{ ...TD, color: doc.assinado ? '#34d399' : TX3, fontSize: 11.5 }}>{fmtDate(doc.assinado) || '—'}</td>
                    <td style={TD}>
                      {doc.link
                        ? <Btn onClick={() => navigator.clipboard.writeText(doc.link).catch(() => {})} style={{ fontSize: 11, padding: '3px 8px' }}>Copiar link</Btn>
                        : <span style={{ color: TX3 }}>—</span>}
                    </td>
                    <td style={TD}>
                      {(() => {
                        const s = aplisLocal[doc.requisicao] || aplisData[doc.requisicao]?.status
                        if (s) return <AplisStatusBadge status={s} />
                        if (!doc.assinado) return <span style={{ color: TX3 }}>—</span>
                        return <Btn onClick={() => anexar(doc.requisicao)} disabled={!!anexandoReq} variant="primary" style={{ fontSize: 11, padding: '3px 10px' }}>{anexandoReq === doc.requisicao ? 'Anexando…' : 'Anexar ao APLIS'}</Btn>
                      })()}
                    </td>
                  </TRow>
                ))
              }
            </tbody>
          </table>
        </div>
        {totalPages > 1 && (
          <div style={{ padding: '12px 16px', borderTop: `0.5px solid ${BDR}`, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
            <Btn onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}>← Anterior</Btn>
            <span style={{ color: TX2, fontSize: 12 }}>Página {page} de {totalPages}</span>
            <Btn onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}>Próxima →</Btn>
          </div>
        )}
      </Card>

      {/* Preview modal */}
      {previewReq && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.7)', zIndex: 90, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div style={{ width: 'min(1400px,96vw)', maxHeight: '92vh', overflow: 'auto', background: SURF, border: `0.5px solid ${BDR}`, borderRadius: 12, padding: '14px 16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              <span style={{ color: TX2, fontSize: 12 }}>Requisição</span>
              <span style={{ color: '#818cf8', fontFamily: 'monospace', fontSize: 12 }}>{previewReq}</span>
              <div style={{ flex: 1 }} />
              <Btn onClick={() => { setPreviewReq(''); setPreviewSel(null) }}>Fechar</Btn>
            </div>
            {previewLoading && <div style={{ color: TX2, fontSize: 12 }}>Carregando imagens…</div>}
            {previewError  && <div style={{ color: '#f87171', fontSize: 12 }}>{previewError}</div>}
            {!previewLoading && !previewError && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {previewSel && (
                  <div style={{ background: BG, border: `0.5px solid ${BDR}`, borderRadius: 8, padding: 8 }}>
                    <div style={{ color: TX2, fontSize: 11, marginBottom: 8, fontFamily: 'monospace', wordBreak: 'break-all' }}>{previewSel.name}</div>
                    {(previewSel.name || '').toLowerCase().endsWith('.pdf')
                      ? <iframe src={`${API}${previewSel.url}#zoom=page-width`} title={previewSel.name} style={{ width: '100%', height: '70vh', border: 'none', borderRadius: 6 }} />
                      : <div style={{ display: 'flex', justifyContent: 'center' }}><img src={`${API}${previewSel.url}`} alt={previewSel.name} style={{ maxWidth: '100%', maxHeight: '70vh', objectFit: 'contain', borderRadius: 6 }} /></div>
                    }
                  </div>
                )}
                <div style={{ display: 'flex', gap: 6, overflowX: 'auto' }}>
                  {previewItems.map((it, idx) => (
                    <button key={`${it.name}-${idx}`} onClick={() => setPreviewSel(it)} style={{ minWidth: 200, textAlign: 'left', background: previewSel?.name === it.name ? SURF2 : BG, border: `0.5px solid ${previewSel?.name === it.name ? '#60a5fa' : BDR}`, borderRadius: 7, color: TX, padding: '7px 10px', cursor: 'pointer', fontSize: 11, fontFamily: 'monospace' }}>{it.name}</button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Aba WhatsApp ──────────────────────────────────────────────────────────────
function AbaWhatsApp() {
  const [items, setItems]           = useState([])
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState(null)
  const [filtro, setFiltro]         = useState('')
  const [arquivo, setArquivo]       = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [visibleItems, setVisibleItems] = useState(10)

  const fetchMensagens = useCallback(async (silent = false) => {
    if (!silent) { setLoading(true); setError(null) }
    try {
      const r = await fetch(`${API}/api/whatsapp/mensagens?limit=1000&_ts=${Date.now()}`, { cache: 'no-store' })
      const d = await r.json()
      if (d.error) { setError(d.error); setItems([]); return }
      setItems(d.items || []); setArquivo(d.file || '')
    } catch { setError('Falha ao carregar mensagens') }
    finally { if (!silent) setLoading(false) }
  }, [])

  useEffect(() => { fetchMensagens() }, [fetchMensagens])
  useVisibleInterval(useCallback(() => { if (autoRefresh) fetchMensagens(true) }, [autoRefresh, fetchMensagens]), 60000)

  const lista = filtro.trim()
    ? items.filter(i => (i.telefone_original || '').includes(filtro) || (i.telefone_destino || '').includes(filtro) || (i.status || '').toLowerCase().includes(filtro.toLowerCase()) || (i.mensagem || '').toLowerCase().includes(filtro.toLowerCase()))
    : items

  useEffect(() => { setVisibleItems(10) }, [filtro, items.length])

  const listaExibida = lista.slice(0, visibleItems)
  const faltantes    = Math.max(0, lista.length - listaExibida.length)

  const statusColor = s => {
    if ((s || '').startsWith('ERRO'))     return 'red'
    if ((s || '').startsWith('RECEBIDA')) return 'blue'
    if (s === 'ENVIADA')                  return 'green'
    return 'yellow'
  }
  const statusLabel = s => {
    const st = String(s || '').toUpperCase()
    if (!st) return 'Pendente'
    if (st.startsWith('RECEBIDA_SIM'))    return 'Confirmado'
    if (st.startsWith('RECEBIDA_NAO'))    return 'Recusado'
    if (st.startsWith('RECEBIDA_LIBERAR')) return 'Liberado'
    if (st.startsWith('RECEBIDA_PULAR'))  return 'Não liberado'
    if (st.startsWith('RECEBIDA'))        return 'Resposta recebida'
    if (st === 'ENVIADA')                 return 'Enviada'
    if (st.startsWith('ERRO'))            return 'Falha'
    return 'Processando'
  }
  const resumo = msg => {
    if (!msg) return '—'
    if (msg.includes('Deseja receber o link de assinatura')) return 'Solicitação de confirmação enviada.'
    if (msg.includes('Documento Enviado com Sucesso'))       return 'Notificação de envio concluída.'
    if (msg.includes('[LIBERACAO TESTE - AUTENTIQUE]'))      return 'Aguardando liberação do operador.'
    return 'Comunicação registrada.'
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <Input value={filtro} onChange={e => setFiltro(e.target.value)} placeholder="Filtrar por telefone, status ou texto…" style={{ width: 340 }} />
        <span style={{ color: TX3, fontSize: 12 }}>{items.length} mensagem(ns)</span>
        {arquivo && <span style={{ color: TX3, fontSize: 11 }}>· {arquivo}</span>}
        <div style={{ flex: 1 }} />
        <Btn onClick={() => setAutoRefresh(v => !v)} variant={autoRefresh ? 'primary' : 'ghost'} style={{ fontSize: 11 }}>{autoRefresh ? 'Tempo real ON' : 'Tempo real OFF'}</Btn>
        <Btn onClick={fetchMensagens}>↻ Atualizar</Btn>
      </div>
      {error && <div style={{ color: '#f87171', fontSize: 12 }}>{error}</div>}
      <Card>
        <div style={{ maxHeight: '60vh', overflowY: 'auto', overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>{['Data/Hora', 'Origem', 'Destino', 'Status', 'Resumo'].map(h => <th key={h} style={TH}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {loading
                ? <tr><td colSpan={5} style={{ ...TD, textAlign: 'center', color: TX3, padding: 40 }}>Carregando…</td></tr>
                : lista.length === 0
                ? <tr><td colSpan={5} style={{ ...TD, textAlign: 'center', color: TX3, padding: 40 }}>Nenhuma mensagem encontrada.</td></tr>
                : listaExibida.map((item, idx) => (
                  <TRow key={`${item.data_hora}-${idx}`}>
                    <td style={{ ...TD, color: TX2, whiteSpace: 'nowrap', fontSize: 11.5 }}>{fmtDate(item.data_hora) || item.data_hora || '—'}</td>
                    <td style={{ ...TD, fontFamily: 'monospace', color: TX2, fontSize: 11.5 }}>{item.telefone_original || '—'}</td>
                    <td style={{ ...TD, fontFamily: 'monospace', color: '#818cf8', fontSize: 11.5 }}>{item.telefone_destino || '—'}</td>
                    <td style={TD}><Badge color={statusColor(item.status)}>{statusLabel(item.status)}</Badge></td>
                    <td style={{ ...TD, color: '#cbd5e1', maxWidth: 380, fontSize: 12 }}>{resumo(item.mensagem)}</td>
                  </TRow>
                ))
              }
            </tbody>
          </table>
        </div>
      </Card>
      {!loading && faltantes > 0 && (
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <Btn onClick={() => setVisibleItems(v => Math.min(lista.length, v + 10))}>Mostrar mais {Math.min(10, faltantes)} registros</Btn>
        </div>
      )}
    </div>
  )
}

// ── Aba Faturamento ───────────────────────────────────────────────────────────
function AbaFaturamento({ running, logs, totalLines, runContext, executionSnapshot, modoTeste, onRunStarted, onStop, onOpenLogTab }) {
  const [items, setItems]             = useState([])
  const [visibleItems, setVisibleItems] = useState(10)
  const [filtroWA, setFiltroWA]       = useState(false)
  const [enviandoReq, setEnviandoReq] = useState('')
  const [assinandoReq, setAssinandoReq] = useState('')
  const [desfazendoReq, setDesfazendoReq] = useState('')
  const [resumo, setResumo]           = useState({ total:0, enviados:0, assinados:0, pendentes:0, nao_enviados:0, rejeitados:0 })
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState(null)
  const [aplisMsg, setAplisMsg]       = useState(null)
  const [aplisLocal, setAplisLocal]   = useState({})
  const [search, setSearch]           = useState('')
  const [convenio, setConvenio]       = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [runIni, setRunIni]           = useState(formatDateLocal(new Date()))
  const [runFim, setRunFim]           = useState(formatDateLocal(new Date()))
  const [previewReq, setPreviewReq]   = useState('')
  const [previewItems, setPreviewItems] = useState([])
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError]     = useState(null)
  const [previewSel, setPreviewSel]         = useState(null)
  const [ger, setGer]                 = useState({ summary: null, records: [] })
  const { aplisData, refresh: refA }  = useAplisStatus()
  const [anexandoReq, setAnexandoReq] = useState('')

  const fetchStatus = useCallback(async (silent = false) => {
    if (!silent) { setLoading(true); setError(null) }
    try {
      const p = new URLSearchParams()
      if (search.trim())   p.set('search', search.trim())
      if (convenio.trim()) p.set('convenio', convenio.trim())
      const q = p.toString() ? `?${p}` : ''
      const r = await fetch(`${API}/api/faturamento/status${q}`)
      const d = await r.json()
      if (d.error) { setError(d.error); setItems([]); return }
      setItems(d.items || [])
      setResumo(d.resumo || { total:0, enviados:0, assinados:0, pendentes:0, nao_enviados:0, rejeitados:0 })
    } catch { if (!silent) { setError('Falha ao carregar faturamento'); setItems([]) } }
    finally { if (!silent) setLoading(false) }
  }, [search, convenio])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  const shouldFast = running || Boolean(executionSnapshot?.running)

  const fetchGer = useCallback(async (silent = false) => {
    try {
      const r = await fetch(`${API}/api/gerenciamento/faturamento`)
      const d = await r.json()
      if (!r.ok || d?.error) { if (!silent) setError(d?.error || 'Falha'); return }
      setGer({ summary: d?.summary || null, records: Array.isArray(d?.records) ? d.records : [] })
    } catch { if (!silent) setError('Falha ao carregar gerenciamento') }
  }, [])

  useEffect(() => {
    if (!autoRefresh) return
    const id = setInterval(() => { if (!document.hidden) { fetchStatus(true); fetchGer(true) } }, shouldFast ? 8000 : 120000)
    return () => clearInterval(id)
  }, [autoRefresh, fetchStatus, fetchGer, shouldFast])

  useEffect(() => { fetchGer(true) }, [fetchGer])
  useEffect(() => { setVisibleItems(10) }, [search, convenio, items.length, filtroWA])

  const baixar = useCallback(async (path, name) => {
    try {
      const p = new URLSearchParams()
      if (search.trim())   p.set('search', search.trim())
      if (convenio.trim()) p.set('convenio', convenio.trim())
      const r = await fetch(`${API}${path}${p.toString() ? '?' + p : ''}`)
      if (!r.ok || (r.headers.get('content-type') || '').includes('application/json')) { const d = await r.json().catch(() => ({})); setError(d.error || 'Falha ao baixar'); return }
      const blob = await r.blob(); const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); const cd = r.headers.get('content-disposition') || ''
      const m = cd.match(/filename="?([^";]+)"?/i)
      a.href = url; a.download = m?.[1] || name; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
    } catch { setError('Falha ao baixar arquivo') }
  }, [search, convenio])

  const iniciarEnvio = useCallback(async () => {
    setError(null)
    try {
      const r = await fetch(`${API}/api/faturamento/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data_inicial: runIni, data_final: runFim }) })
      const d = await r.json()
      if (d.error) { setError(d.error); return }
      onRunStarted?.(); fetchStatus()
    } catch { setError('Falha ao iniciar envio') }
  }, [runIni, runFim, fetchStatus, onRunStarted])

  const enviarIndividual = useCallback(async (req) => {
    setError(null); setEnviandoReq(req)
    try {
      const r = await fetch(`${API}/api/faturamento/run-individual`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requisicao: req, data_inicial: runIni || null, data_final: runFim || null }) })
      const d = await r.json()
      if (!r.ok || d.error) { setError(d.error || 'Falha'); return }
      onRunStarted?.(); fetchStatus()
    } catch { setError('Falha ao enviar individual') }
    finally { setEnviandoReq('') }
  }, [runIni, runFim, fetchStatus, onRunStarted])

  const marcarAssinado = useCallback(async (req) => {
    setError(null); setAssinandoReq(req)
    try {
      const r = await fetch(`${API}/api/faturamento/requisicao/assinar-realizada`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requisicao: req }) })
      const d = await r.json()
      if (!r.ok || d.error) { setError(d.error || 'Falha'); return }
      fetchStatus()
    } catch { setError('Falha ao marcar assinatura') }
    finally { setAssinandoReq('') }
  }, [fetchStatus])

  const desfazerAssinado = useCallback(async (req) => {
    setError(null); setDesfazendoReq(req)
    try {
      const r = await fetch(`${API}/api/faturamento/requisicao/desfazer-assinatura-realizada`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requisicao: req }) })
      const d = await r.json()
      if (!r.ok || d.error) { setError(d.error || 'Falha'); return }
      fetchStatus()
    } catch { setError('Falha ao desfazer assinatura') }
    finally { setDesfazendoReq('') }
  }, [fetchStatus])

  const salvarTelefone = useCallback(async (req, atual = '') => {
    const valor = window.prompt('Informe o telefone do paciente (com DDD, com ou sem 55).\nDeixe vazio para remover.', atual || '')
    if (valor === null) return
    setError(null)
    try {
      const r = await fetch(`${API}/api/faturamento/telefone`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requisicao: req, telefone: valor }) })
      const d = await r.json()
      if (!r.ok || d.error) { setError(d.error || 'Falha'); return }
      fetchStatus()
    } catch { setError('Falha ao salvar telefone') }
  }, [fetchStatus])

  const abrirImagens = useCallback(async (req) => {
    setPreviewReq(req); setPreviewItems([]); setPreviewError(null); setPreviewLoading(true)
    try {
      const r = await fetch(`${API}/api/requisicoes/${encodeURIComponent(req)}/imagens`)
      const d = await r.json()
      if (d.error) { setPreviewError(d.error); return }
      setPreviewItems(d.items || [])
      if (!(d.items || []).length) setPreviewError('Nenhuma imagem local encontrada.')
    } catch { setPreviewError('Falha ao carregar imagens.') }
    finally { setPreviewLoading(false) }
  }, [])

  const anexarAplis = useCallback(async (req) => {
    setError(null)
    setAplisMsg(null)
    setAnexandoReq(req)
    try {
      const d = await chamarAnexa(req)
      if (d.sucesso) {
        setAplisLocal(prev => ({ ...prev, [req]: 'assinado' }))
        const meta = d.anexo_aplis
        const sufixo = meta
          ? ` (idImagem ${meta.idRequisicaoImagem}, tipo ${meta.tipo}, arquivo ${meta.arquivo}.${String(meta.extensao || '').toLowerCase()})`
          : ''
        setAplisMsg(d.ja_anexado
          ? `Requisição ${req}: guia já estava anexada no APLIS.${sufixo}`
          : `Requisição ${req}: guia anexada com sucesso no APLIS.${sufixo}`)
      } else {
        setAplisLocal(prev => ({ ...prev, [req]: 'erro' }))
        const detalhe = d.detalhe ? ` | ${String(d.detalhe).slice(0, 180)}` : ''
        setError(`${d.erro || 'Falha ao anexar'}${detalhe}`)
      }
      refA()
    } catch (e) {
      setError(`Erro de conexão ao anexar no APLIS: ${e.message}`)
    }
    setAnexandoReq('')
  }, [refA])

  // helpers de badge/label
  const statusDocBadge = s => {
    if (s === 'ASSINADO')   return <Badge color="green">Assinado</Badge>
    if (s === 'REJEITADO')  return <Badge color="red">Recusado</Badge>
    if (s === 'VISUALIZADO')return <Badge color="blue">Visualizado</Badge>
    if (s === 'ENVIADO')    return <Badge color="yellow">Enviado</Badge>
    if (s === 'PENDENTE')   return <Badge color="yellow">Pendente</Badge>
    return <Badge color="gray">Não enviado</Badge>
  }
  const waBadge = raw => {
    const s = String(raw || '').toUpperCase()
    if (!s) return <Badge color="gray">Sem envio</Badge>
    if (s.startsWith('RECEBIDA_SIM'))    return <Badge color="green">Confirmou</Badge>
    if (s.startsWith('RECEBIDA_NAO'))    return <Badge color="red">Recusou</Badge>
    if (s.startsWith('RECEBIDA_LIBERAR')) return <Badge color="blue">Liberado</Badge>
    if (s.startsWith('RECEBIDA_PULAR'))  return <Badge color="yellow">Não liberar</Badge>
    if (s.startsWith('ENVIADA'))         return <Badge color="blue">Enviada</Badge>
    if (s.startsWith('AVISO_ASSINATURA'))return <Badge color="blue">Aviso enviado</Badge>
    if (s.startsWith('ERRO'))            return <Badge color="red">Falha</Badge>
    return <Badge color="gray">Em análise</Badge>
  }
  const motivoBadge = item => {
    const s = String(item?.status_documento || '').toUpperCase()
    if (s !== 'NAO_ENVIADO') return <Badge color="green">Tratado</Badge>
    const code = String(item?.nao_enviado_motivo_code || '').toUpperCase()
    const lbl  = item?.nao_enviado_motivo || 'Sem motivo'
    if (code === 'RECUSA')              return <span title={lbl}><Badge color="red">Recusa</Badge></span>
    if (code === 'ERRO_WHATSAPP')       return <span title={lbl}><Badge color="red">Falha WA</Badge></span>
    if (code === 'AGUARDANDO_LIBERACAO')return <span title={lbl}><Badge color="yellow">Aguardando</Badge></span>
    if (code === 'FLUXO_WHATSAPP')      return <span title={lbl}><Badge color="blue">Fluxo WA</Badge></span>
    if (code === 'REENVIO_MANUAL')      return <span title={lbl}><Badge color="purple">Reenvio manual</Badge></span>
    return <span title={lbl}><Badge color="gray">Não disparado</Badge></span>
  }
  const msgResumo = msg => {
    if (!msg) return '—'
    if (msg.includes('Deseja receber o link de assinatura')) return 'Confirmação enviada ao paciente.'
    if (msg.includes('Documento Enviado com Sucesso'))       return 'Paciente notificado sobre envio.'
    if (msg.includes('[LIBERACAO TESTE - AUTENTIQUE]'))      return 'Aguardando liberação manual.'
    if (modoTeste) return 'Mensagem técnica ocultada (homologação).'
    return msg.length > 90 ? `${msg.slice(0, 90)}…` : msg
  }
  const podeEnviar = item => {
    const s = String(item?.status_documento || '').toUpperCase()
    return s === 'NAO_ENVIADO' || (item?.telefone_override && s !== 'ASSINADO')
  }
  const isMsgEnviada = item => {
    const s = String(item?.whatsapp_status || '').toUpperCase()
    const msg = String(item?.whatsapp_mensagem || '')
    const sd  = String(item?.status_documento || '').toUpperCase()
    return s.startsWith('ENVIADA') || s.startsWith('RECEBIDA_') || s.startsWith('AVISO_ASSINATURA')
      || msg.includes('Deseja receber o link de assinatura') || msg.includes('Documento Enviado com Sucesso')
      || msg.includes('REQ_AVISO:') || (sd && sd !== 'NAO_ENVIADO')
  }

  const fatRodando  = running && runContext?.mode === 'faturamento'
  const outroRodando = running && runContext?.mode && runContext?.mode !== 'faturamento'
  const snap = executionSnapshot || {}
  const execAtiva = Boolean(running || snap?.running)
  const progresso = parseDashboard(logs)
  const nowLabel  = progresso.etapa === 'download' ? `Download ${progresso.dlAtual}/${progresso.dlTotal}`
    : progresso.etapa === 'ia'   ? `IA ${progresso.iaAtual}/${progresso.iaTotal} · Guia ${progresso.currentIaReq || '—'}`
    : progresso.etapa === 'waha' ? `WhatsApp ${progresso.wahaAtual}/${progresso.wahaTotal}`
    : running ? 'Processando faturamento…' : 'Aguardando envio'
  const itemsFiltrados = filtroWA ? items.filter(isMsgEnviada) : items
  const itemsExibidos  = itemsFiltrados.slice(0, visibleItems)
  const faltantes      = Math.max(0, itemsFiltrados.length - itemsExibidos.length)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

      {/* Banner execução ativa */}
      {execAtiva && (
        <div style={{ background: 'rgba(167,139,250,0.08)', border: '0.5px solid rgba(167,139,250,0.2)', borderRadius: 10, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ width: 7, height: 7, borderRadius: '50%', background: '#a78bfa', flexShrink: 0, animation: 'pulse-d 1.5s infinite' }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: '#a78bfa', fontWeight: 500, marginBottom: 2 }}>Execução ativa</div>
            <div style={{ fontSize: 11.5, color: TX2 }}>{nowLabel}</div>
          </div>
          <Btn onClick={onOpenLogTab} style={{ fontSize: 11 }}>Ver log detalhado</Btn>
        </div>
      )}

      {/* Dashboard IA quando rodando */}
      {(execAtiva || logs.length > 0 || snap?.finished_at) && (
        <Dashboard running={running} logs={logs} done={!running && logs.length > 0} executionSnapshot={executionSnapshot} />
      )}

      {/* KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(120px,1fr))', gap: 6 }}>
        {[
          { label: 'Total',         value: resumo.total,       color: TX },
          { label: 'Enviados',      value: resumo.enviados,    color: '#60a5fa' },
          { label: 'Assinados',     value: resumo.assinados,   color: '#34d399' },
          { label: 'Pendentes',     value: resumo.pendentes,   color: '#fbbf24' },
          { label: 'Não enviados',  value: resumo.nao_enviados,color: TX2 },
          { label: 'Rejeitados',    value: resumo.rejeitados,  color: '#f87171' },
        ].map(k => (
          <Card pad key={k.label} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <SectionLabel>{k.label}</SectionLabel>
            <div style={{ fontSize: 26, fontWeight: 400, color: k.color, lineHeight: 1 }}>{k.value ?? 0}</div>
          </Card>
        ))}
      </div>

      {/* Toolbar */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '12px 16px', background: SURF, border: `0.5px solid ${BDR}`, borderRadius: 10 }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Buscar nome, requisição ou convênio…" style={{ flex: 1, minWidth: 200, maxWidth: 300 }} />
          <Input value={convenio} onChange={e => setConvenio(e.target.value)} placeholder="Convênio…" style={{ width: 150 }} />
          <Btn onClick={() => setFiltroWA(v => !v)} variant={filtroWA ? 'primary' : 'ghost'} style={{ fontSize: 11, borderRadius: 99 }}>WA: {filtroWA ? 'só enviadas' : 'todas'}</Btn>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, background: SURF2, border: `0.5px solid ${BDR}`, borderRadius: 7, padding: '0 4px' }}>
            <Input type="date" value={runIni} onChange={e => setRunIni(e.target.value)} style={{ border: 'none', background: 'transparent', width: 130, padding: '6px 8px' }} />
            <span style={{ color: TX3, fontSize: 10 }}>—</span>
            <Input type="date" value={runFim} onChange={e => setRunFim(e.target.value)} style={{ border: 'none', background: 'transparent', width: 130, padding: '6px 8px' }} />
          </div>
          {fatRodando
            ? <Btn onClick={onStop} variant="danger">■ Parar</Btn>
            : <Btn onClick={iniciarEnvio} disabled={outroRodando} variant="primary">▶ Envio separado</Btn>
          }
        </div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <Btn onClick={() => baixar('/api/faturamento/export/pendentes', 'pendentes.csv')} style={{ fontSize: 11 }}>CSV pendentes</Btn>
          <Btn onClick={() => baixar('/api/faturamento/export/assinados', 'assinados.csv')} style={{ fontSize: 11 }}>CSV assinados</Btn>
          <Btn onClick={() => baixar('/api/faturamento/download/assinados', 'assinados.zip')} variant="primary" style={{ fontSize: 11 }}>Baixar ZIP</Btn>
          <div style={{ flex: 1 }} />
          <Btn onClick={fetchStatus} style={{ fontSize: 11 }}>↻ Atualizar</Btn>
          <Btn onClick={() => setAutoRefresh(v => !v)} variant={autoRefresh ? 'primary' : 'ghost'} style={{ fontSize: 11 }}>{autoRefresh ? 'Tempo real' : 'Pausado'}</Btn>
        </div>
      </div>

      {error && <div style={{ color: '#f87171', fontSize: 12, padding: '8px 12px', background: 'rgba(248,113,113,0.08)', border: '0.5px solid rgba(248,113,113,0.2)', borderRadius: 8 }}>{error}</div>}
      {aplisMsg && <div style={{ color: '#34d399', fontSize: 12, padding: '8px 12px', background: 'rgba(52,211,153,0.08)', border: '0.5px solid rgba(52,211,153,0.25)', borderRadius: 8 }}>{aplisMsg}</div>}
      {outroRodando && <div style={{ color: '#fbbf24', fontSize: 12 }}>Análise geral em execução. Aguarde para iniciar faturamento.</div>}

      {/* Histórico de execuções */}
      <ExecHistory ger={ger} title="Histórico de Execuções — Faturamento" />

      {/* Tabela de requisições */}
      <Card>
        <div style={{ maxHeight: '62vh', overflowY: 'auto', overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                {['Paciente','Requisição','Convênio','Documento','Motivo','Enviado','Assinado','APLIS',
                  <span key="wa" onClick={() => setFiltroWA(v=>!v)} style={{cursor:'pointer',color:filtroWA?'#60a5fa':TX3}}>WhatsApp{filtroWA?' ▼':''}</span>,
                  'Ações'].map((h, i) => <th key={i} style={TH}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {loading
                ? <tr><td colSpan={10} style={{ ...TD, textAlign: 'center', color: TX3, padding: 40 }}>Carregando…</td></tr>
                : itemsFiltrados.length === 0
                ? <tr><td colSpan={10} style={{ ...TD, textAlign: 'center', color: TX3, padding: 40 }}>Nenhuma requisição encontrada.</td></tr>
                : itemsExibidos.map((it, idx) => {
                  const bloqueado = outroRodando || fatRodando
                  return (
                    <TRow key={`${it.requisicao}-${idx}`}>
                      <td style={TD}>{it.nome}</td>
                      <td style={{ ...TD, minWidth: 110 }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                          <button onClick={() => abrirImagens(it.requisicao)} style={{ background:'none',border:'none',color:'#818cf8',cursor:'pointer',fontFamily:'monospace',fontSize:12,padding:0,textAlign:'left' }}>{it.requisicao}</button>
                          {it.telefone_override && <span style={{ fontSize: 10, color: TX3, fontFamily: 'monospace' }}>{it.telefone_override}</span>}
                        </div>
                      </td>
                      <td style={{ ...TD, color: TX2 }}>{it.convenio}</td>
                      <td style={TD}>{statusDocBadge(it.status_documento)}</td>
                      <td style={TD}>{motivoBadge(it)}</td>
                      <td style={{ ...TD, color: TX2, fontSize: 11.5, whiteSpace: 'nowrap' }}>{fmtDate(it.enviado_em) || '—'}</td>
                      <td style={{ ...TD, color: '#34d399', fontSize: 11.5, whiteSpace: 'nowrap' }}>{fmtDate(it.assinado_em) || '—'}</td>
                      <td style={TD}>
                        {(() => {
                          const s = aplisLocal[it.requisicao] || aplisData[it.requisicao]?.status
                          if (s) return <AplisStatusBadge status={s} />
                          if (String(it.status_documento||'').toUpperCase() !== 'ASSINADO') return <span style={{color:TX3}}>—</span>
                          return <Btn onClick={() => anexarAplis(it.requisicao)} disabled={!!anexandoReq} variant="primary" style={{ fontSize: 10, padding: '3px 8px' }}>{anexandoReq === it.requisicao ? 'Anexando…' : 'Anexar APLIS'}</Btn>
                        })()}
                      </td>
                      <td style={TD}><span title={msgResumo(it.whatsapp_mensagem)}>{waBadge(it.whatsapp_status)}</span></td>
                      <td style={{ ...TD, minWidth: 170 }}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                          <Btn onClick={() => enviarIndividual(it.requisicao)} disabled={bloqueado || enviandoReq === it.requisicao || !podeEnviar(it)} variant="primary" title={it.telefone_override ? 'Reenviar via telefone manual' : 'Enviar documento para assinatura'} style={{ fontSize: 10, padding: '3px 8px' }}>{enviandoReq === it.requisicao ? 'Enviando…' : 'Enviar'}</Btn>
                          <Btn onClick={() => marcarAssinado(it.requisicao)} disabled={bloqueado || assinandoReq === it.requisicao || String(it.status_documento||'').toUpperCase()==='ASSINADO'} style={{ fontSize: 10, padding: '3px 8px' }}>{assinandoReq === it.requisicao ? '…' : 'Marcar assinado'}</Btn>
                          {it.assinatura_manual && <Btn onClick={() => desfazerAssinado(it.requisicao)} disabled={bloqueado || desfazendoReq === it.requisicao} variant="danger" style={{ fontSize: 10, padding: '3px 8px' }}>{desfazendoReq === it.requisicao ? '…' : 'Desfazer'}</Btn>}
                          <Btn onClick={() => salvarTelefone(it.requisicao, it.telefone_override||'')} disabled={bloqueado} title={it.telefone_override ? `Tel atual: ${it.telefone_override}` : 'Adicionar telefone manual'} style={{ fontSize: 10, padding: '3px 8px' }}>{it.telefone_override ? 'Tel ✎' : '+ Tel'}</Btn>
                        </div>
                      </td>
                    </TRow>
                  )
                })
              }
            </tbody>
          </table>
        </div>
      </Card>

      {!loading && faltantes > 0 && (
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <Btn onClick={() => setVisibleItems(v => Math.min(itemsFiltrados.length, v + 10))}>Mostrar mais {Math.min(10, faltantes)} requisições</Btn>
        </div>
      )}

      {/* Preview modal */}
      {previewReq && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.7)', zIndex: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div style={{ width: 'min(1400px,96vw)', maxHeight: '92vh', overflow: 'auto', background: SURF, border: `0.5px solid ${BDR}`, borderRadius: 12, padding: '14px 16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              <span style={{ color: TX2, fontSize: 12 }}>Imagens da requisição</span>
              <span style={{ color: '#818cf8', fontFamily: 'monospace', fontSize: 12 }}>{previewReq}</span>
              <div style={{ flex: 1 }} />
              <Btn onClick={() => { setPreviewReq(''); setPreviewSel(null) }}>Fechar</Btn>
            </div>
            {previewLoading && <div style={{ color: TX2, fontSize: 12 }}>Carregando…</div>}
            {previewError   && <div style={{ color: '#f87171', fontSize: 12 }}>{previewError}</div>}
            {!previewLoading && !previewError && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {previewSel && (
                  <div style={{ background: BG, border: `0.5px solid ${BDR}`, borderRadius: 8, padding: 8 }}>
                    <div style={{ color: TX2, fontSize: 11, marginBottom: 8, fontFamily: 'monospace', wordBreak: 'break-all' }}>{previewSel.name}</div>
                    {(previewSel.name || '').toLowerCase().endsWith('.pdf')
                      ? <iframe src={`${API}${previewSel.url}`} title={previewSel.name} style={{ width: '100%', height: '70vh', border: 'none', borderRadius: 6 }} />
                      : <div style={{ display: 'flex', justifyContent: 'center' }}><img src={`${API}${previewSel.url}`} alt={previewSel.name} style={{ maxWidth: '100%', maxHeight: '70vh', objectFit: 'contain', borderRadius: 6 }} /></div>
                    }
                  </div>
                )}
                <div style={{ display: 'flex', gap: 6, overflowX: 'auto' }}>
                  {previewItems.map((it, i) => (
                    <button key={i} onClick={() => setPreviewSel(it)} style={{ minWidth: 200, background: previewSel?.name === it.name ? SURF2 : BG, border: `0.5px solid ${previewSel?.name === it.name ? '#60a5fa' : BDR}`, borderRadius: 7, color: TX, padding: '7px 10px', cursor: 'pointer', fontSize: 11, fontFamily: 'monospace' }}>{it.name}</button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Painel histórico de execuções (reutilizável) ───────────────────────────────
function ExecHistory({ ger, title }) {
  const { summary, records } = ger
  return (
    <Card>
      <div style={{ padding: '14px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: TX }}>{title}</div>
          <div style={{ fontSize: 11, color: TX3, marginTop: 2 }}>Últimos {records?.length ?? 0} registros</div>
        </div>
        {summary?.ultimo_status && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <ExecStatusBadge status={summary.ultimo_status} />
            <span style={{ fontSize: 11, color: TX3 }}>{fmtDate(summary.ultimo_started_at)}</span>
          </div>
        )}
      </div>
      <Divider />
      {/* KPI strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)' }}>
        {[
          { label: 'Enviados hoje',     value: <span style={{ color: '#60a5fa', fontSize: 22 }}>{summary?.enviados_hoje ?? 0}</span> },
          { label: 'Variação vs ontem', value: <TrendArrow value={summary?.variacao_hoje_vs_ontem ?? 0} /> },
          { label: 'Média 7d',          value: <span style={{ color: TX, fontSize: 22 }}>{summary?.media_enviados_7d ?? 0}</span> },
          { label: 'Taxa conclusão 7d', value: <span style={{ color: '#34d399', fontSize: 22 }}>{summary?.taxa_conclusao_7d ?? 0}%</span> },
          { label: 'Execuções 7d',      value: <span style={{ color: TX2, fontSize: 22 }}>{summary?.execucoes_7d ?? 0}</span> },
        ].map((k, i) => (
          <div key={i} style={{ padding: '14px 20px', borderRight: i < 4 ? `0.5px solid ${BDR}` : 'none' }}>
            <SectionLabel>{k.label}</SectionLabel>
            <div style={{ marginTop: 8 }}>{k.value}</div>
          </div>
        ))}
      </div>
      {records?.length > 0 && (
        <>
          <Divider />
          <div style={{ padding: '14px 20px' }}>
            <HistoryChart records={records} />
          </div>
          <Divider />
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['Data / Hora','Período','Status','Alvo','Enviados','Taxa','Duração'].map(h => <th key={h} style={TH}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {[...records].reverse().map((r, i) => {
                  const taxa   = r.total_alvo > 0 ? Math.round((r.enviados / r.total_alvo) * 100) : null
                  return (
                    <TRow key={i}>
                      <td style={{ ...TD, color: TX2, fontSize: 11.5, whiteSpace: 'nowrap' }}>{fmtDate(r.started_at) ?? '—'}</td>
                      <td style={{ ...TD, color: TX3, fontSize: 11.5, whiteSpace: 'nowrap' }}>{r.data_inicial && r.data_final ? `${r.data_inicial} → ${r.data_final}` : '—'}</td>
                      <td style={TD}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          <div><ExecStatusBadge status={r.status} /></div>
                          {r.last_line && <div title={r.last_line} style={{ color: TX3, fontSize: 10.5, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.last_line}</div>}
                        </div>
                      </td>
                      <td style={{ ...TD, color: TX2, fontWeight: 500 }}>{r.total_alvo ?? '—'}</td>
                      <td style={{ ...TD, color: '#60a5fa', fontWeight: 500 }}>{r.enviados ?? '—'}</td>
                      <td style={{ ...TD, color: taxa === null ? TX3 : taxa >= 80 ? '#34d399' : taxa >= 50 ? '#fbbf24' : '#f87171', fontWeight: 500 }}>{taxa !== null ? `${taxa}%` : '—'}</td>
                      <td style={{ ...TD, color: TX3 }}>{fmtExecDuration(r.started_at, r.finished_at)}</td>
                    </TRow>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      {!records?.length && (
        <div style={{ padding: 40, color: TX3, fontSize: 13, textAlign: 'center' }}>Nenhuma execução registrada ainda.</div>
      )}
    </Card>
  )
}

// ── App principal ─────────────────────────────────────────────────────────────
export default function App() {
  const [aba, setAba]           = useState(() => { try { return localStorage.getItem('aba_ativa') || 'analise' } catch { return 'analise' } })
  const [dataInicial, setDataInicial] = useState(formatDateLocal(new Date()))
  const [dataFinal,   setDataFinal]   = useState(formatDateLocal(new Date()))
  const [requisicoesEspecificas, setRequisicoesEspecificas] = useState('')
  const [modoTeste,   setModoTeste]   = useState(false)
  const [tarefaAplis, setTarefaAplis] = useState(false)
  const [running,     setRunning]     = useState(false)
  const [logs,        setLogs]        = useState([])
  const [totalLines,  setTotalLines]  = useState(0)
  const [error,       setError]       = useState(null)
  const [backendOk,   setBackendOk]   = useState(null)
  const [pinned,      setPinned]      = useState(true)
  const [showLog,     setShowLog]     = useState(false)
  const [modoClaro,   setModoClaro]   = useState(() => localStorage.getItem('modo_claro') === '1')
  const [semTelInfo,  setSemTelInfo]  = useState({ ok: false, file: '', updated_at: null, error: null })
  const [runContext,  setRunContext]   = useState(() => { try { const raw = localStorage.getItem('run_context_v1'); return raw ? JSON.parse(raw) : { mode: null, startedAt: null, finishedAt: null } } catch { return { mode: null, startedAt: null, finishedAt: null } } })
  const [execSnap,    setExecSnap]    = useState(null)
  const [gerDiario,   setGerDiario]   = useState({ summary: null, records: [] })
  const [enviandoReq, setEnviandoReq] = useState('')

  const esRef   = useRef(null)
  const pinnedR = useRef(true)
  useEffect(() => { pinnedR.current = pinned }, [pinned])
  useEffect(() => { try { localStorage.setItem('aba_ativa', aba) } catch {} }, [aba])
  useEffect(() => { try { localStorage.setItem('run_context_v1', JSON.stringify(runContext || {})) } catch {} }, [runContext])

  const startStream = useCallback((opts = {}) => {
    setError(null)
    if (opts.reset) { setLogs([]); setTotalLines(0) }
    if (opts.keepPinned !== false) setPinned(true)
    if (esRef.current) esRef.current.close()
    const es = new EventSource(`${API}/api/logs`)
    esRef.current = es
    es.onmessage = e => {
      const { line } = JSON.parse(e.data)
      if (line === '__DONE__') { setRunning(false); setRunContext(p => ({ ...(p||{}), finishedAt: new Date().toISOString() })); es.close(); return }
      setTotalLines(p => p + 1)
      setLogs(p => { const n = [...p, line]; return n.length > MAX_LOG_LINES ? n.slice(-MAX_LOG_LINES) : n })
    }
    es.onerror = () => { setRunning(false); es.close() }
  }, [])

  useEffect(() => {
    let alive = true
    fetch(`${API}/api/logs/history`).then(r => r.json()).then(d => {
      if (!alive) return
      const lines = Array.isArray(d?.lines) ? d.lines : []
      setTotalLines(lines.length)
      setLogs(lines.length > MAX_LOG_LINES ? lines.slice(-MAX_LOG_LINES) : lines)
    }).catch(() => {})
    return () => { alive = false }
  }, [])

  useEffect(() => {
    let es
    const connect = () => {
      if (es) es.close()
      es = new EventSource(`${API}/api/dashboard/stream`)
      es.onmessage = e => {
        try {
          const d = JSON.parse(e.data)
          if (d.status) {
            setModoTeste(d.status.modo_teste); setTarefaAplis(Boolean(d.status.criar_tarefa_aplis))
            setRunning(d.status.running); setBackendOk(true)
            if (d.status.running && !esRef.current) startStream({ reset: false, keepPinned: false })
          }
          if (d.faturamento_exec) {
            const snap = d.faturamento_exec; setExecSnap(snap)
            if (snap?.started_at) setRunContext(prev => {
              const pTs = prev?.startedAt ? new Date(prev.startedAt).getTime() : 0
              const sTs = new Date(snap.started_at).getTime()
              return sTs >= pTs ? { mode: 'faturamento', startedAt: snap.started_at, finishedAt: snap.finished_at || null } : prev
            })
          }
          if (d.gerenciamento_diario) setGerDiario({ summary: d.gerenciamento_diario.summary || null, records: Array.isArray(d.gerenciamento_diario.records) ? d.gerenciamento_diario.records : [] })
        } catch {}
      }
      es.onerror = () => setBackendOk(false)
    }
    connect()
    return () => { if (es) es.close() }
  }, [startStream])

  const handleScroll = useCallback(e => { const el = e.currentTarget; setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 40) }, [])

  const saveConfig = useCallback(async patch => {
    try { await fetch(`${API}/api/config`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) }) }
    catch { setError('Falha ao salvar configuração') }
  }, [])

  const handleModoTeste   = useCallback(v => { setModoTeste(v);   saveConfig({ modo_teste: v }) }, [saveConfig])
  const handleTarefaAplis = useCallback(v => { setTarefaAplis(v); saveConfig({ criar_tarefa_aplis: v }) }, [saveConfig])
  const handleModoClaro   = useCallback(v => { setModoClaro(v);   localStorage.setItem('modo_claro', v ? '1' : '0') }, [])

  const fetchSemTel = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/exports/sem-telefone/latest`); const d = await r.json()
      if (!r.ok || !d?.ok) { setSemTelInfo({ ok: false, file: '', updated_at: null, error: d?.error || 'Nenhum arquivo.' }); return }
      setSemTelInfo({ ok: true, file: d.file || '', updated_at: d.updated_at || null, error: null })
    } catch { setSemTelInfo({ ok: false, file: '', updated_at: null, error: 'Falha ao consultar.' }) }
  }, [])
  useEffect(() => { fetchSemTel() }, [fetchSemTel])

  const fetchGerDiario = useCallback(async (silent = false) => {
    try {
      const r = await fetch(`${API}/api/gerenciamento/diario`); const d = await r.json()
      if (!r.ok || d?.error) { if (!silent) setError(d?.error || 'Falha'); return }
      setGerDiario({ summary: d?.summary || null, records: Array.isArray(d?.records) ? d.records : [] })
    } catch { if (!silent) setError('Falha ao consultar gerenciamento') }
  }, [])
  useEffect(() => { fetchGerDiario(true) }, [fetchGerDiario])

  const handleExportSemTel = useCallback(async () => {
    setError(null)
    try {
      const r = await fetch(`${API}/api/exports/sem-telefone/download`)
      if (!r.ok) { const d = await r.json().catch(() => ({})); setError(d.error || 'Sem CSV disponível'); return }
      const blob = await r.blob(); const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); const cd = r.headers.get('content-disposition') || ''
      const m = cd.match(/filename="?([^";]+)"?/i)
      a.href = url; a.download = m?.[1] || `sem_telefone_${Date.now()}.csv`
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
      fetchSemTel()
    } catch { setError('Falha ao exportar') }
  }, [fetchSemTel])

  const handleRun = useCallback(async () => {
    setError(null); setLogs([]); setTotalLines(0); setPinned(true); setShowLog(false)
    try {
      const r = await fetch(`${API}/api/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data_inicial: dataInicial, data_final: dataFinal, requisicoes: requisicoesEspecificas }) })
      const d = await r.json()
      if (d.error) { setError(d.error); return }
      setRunning(true); setRunContext({ mode: 'analise', startedAt: new Date().toISOString(), finishedAt: null })
    } catch { setError('Não foi possível conectar ao backend'); return }
    startStream({ reset: true, keepPinned: true })
  }, [dataInicial, dataFinal, requisicoesEspecificas, startStream])

  const enviarIndividual = useCallback(async (req) => {
    setError(null); setEnviandoReq(req)
    try {
      const r = await fetch(`${API}/api/faturamento/run-individual`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          requisicao: req,
          data_inicial: dataInicial || null,
          data_final: dataFinal || null
        })
      })
      const d = await r.json()
      if (!r.ok || d.error) { setError(d.error || 'Falha'); return }
      setRunning(true)
      setRunContext({ mode: 'faturamento', startedAt: new Date().toISOString(), finishedAt: null })
      startStream({ reset: true, keepPinned: true })
    } catch { setError('Falha ao enviar individual') }
    finally { setEnviandoReq('') }
  }, [dataInicial, dataFinal, startStream])

  const handleStop = useCallback(async (opts = {}) => {
    try { await fetch(`${API}/api/stop`, { method: 'POST' }) } catch {}
    setRunContext(p => ({ ...(p||{}), finishedAt: new Date().toISOString() }))
    setRunning(false); if (esRef.current) esRef.current.close()
    if (opts.clearVisual) {
      setLogs([]); setTotalLines(0); setPinned(true)
      setExecSnap(p => p ? { ...p, running: false, etapa: 'cancelado' } : p)
    }
  }, [])

  const TABS = [
    { id: 'analise',    label: 'Análise' },
    { id: 'documentos', label: 'Documentos Autentique' },
    { id: 'whatsapp',   label: 'WhatsApp Mensagens' },
  ]

  const MOSTRAR_FATURAMENTO = false
  if (MOSTRAR_FATURAMENTO) {
    TABS.push({ id: 'faturamento', label: 'Faturamento ★' })
  }

  return (
    <div style={{ minHeight: '100vh', background: BG, display: 'flex', flexDirection: 'column', filter: modoClaro ? 'invert(1) hue-rotate(180deg)' : 'none' }}>

      {/* ── Header ── */}
      <header style={{ height: 52, background: 'rgba(11,13,18,0.95)', backdropFilter: 'blur(10px)', borderBottom: `0.5px solid ${BDR}`, padding: '0 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', position: 'sticky', top: 0, zIndex: 50, flexShrink: 0 }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ fontWeight: 600, fontSize: 15, letterSpacing: '-.03em', color: TX }}>
            LAB<span style={{ color: '#f97316' }}>.</span>
          </div>
          <div style={{ width: 1, height: 16, background: BDR }} />
          <div style={{ fontSize: 12, color: TX2 }}>Painel de Assinaturas</div>
        </div>

        {/* Right controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          {/* Status chip */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: 'rgba(255,255,255,0.04)', border: `0.5px solid ${BDR}`, borderRadius: 99, marginRight: 12 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: backendOk === null ? '#fbbf24' : backendOk ? '#34d399' : '#f87171', display: 'inline-block', flexShrink: 0, animation: backendOk ? 'pulse-d 2.5s ease-in-out infinite' : 'none' }} />
            <span style={{ fontSize: 11, color: backendOk ? TX2 : '#f87171' }}>{backendOk === null ? 'Conectando…' : backendOk ? 'Online' : 'Indisponível'}</span>
          </div>

          {/* Toggles */}
          {[
            { label: 'Modo teste',        checked: modoTeste,   onChange: handleModoTeste,   active: modoTeste,   activeColor: '#a78bfa' },
            { label: 'Criar tarefa APLIS',checked: tarefaAplis, onChange: handleTarefaAplis, active: tarefaAplis, activeColor: '#34d399' },
            { label: 'Modo claro',        checked: modoClaro,   onChange: handleModoClaro,   active: modoClaro,   activeColor: '#60a5fa' },
          ].map(t => (
            <div key={t.label} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', borderRadius: 7, background: t.active ? 'rgba(255,255,255,0.04)' : 'transparent' }}>
              <span style={{ fontSize: 10.5, color: t.active ? t.activeColor : TX3, letterSpacing: '.02em' }}>{t.label}</span>
              <Toggle checked={t.checked} onChange={t.onChange} disabled={running && t.label !== 'Modo claro'} />
            </div>
          ))}
        </div>
      </header>

      {/* Banner homologação */}
      {modoTeste && (
        <div style={{ background: 'rgba(167,139,250,0.06)', borderBottom: '0.5px solid rgba(167,139,250,0.15)', padding: '6px 28px', display: 'flex', alignItems: 'center', gap: 8 }}>
          <Badge color="purple">HOMOLOGAÇÃO</Badge>
          <span style={{ fontSize: 11, color: '#7c6db0' }}>Ambiente de validação — dados podem ser de simulação.</span>
        </div>
      )}

      {/* ── Tabs ── */}
      <div style={{ padding: '10px 28px 0', borderBottom: `0.5px solid ${BDR}`, background: BG }}>
        <div style={{ display: 'inline-flex', gap: 2, background: 'rgba(255,255,255,0.04)', border: `0.5px solid ${BDR}`, borderRadius: 9, padding: 3 }}>
          {TABS.map(t => <Pill key={t.id} label={t.label} active={aba === t.id} onClick={() => setAba(t.id)} />)}
        </div>
      </div>

      {/* ── Content ── */}
      <main style={{ flex: 1, padding: '20px 28px', display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 1440, width: '100%', margin: '0 auto' }}>

        {/* ── Aba Análise ── */}
        {aba === 'analise' && (<>
          {/* Toolbar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '10px 14px', background: SURF, border: `0.5px solid ${BDR}`, borderRadius: 10 }}>
            <span style={{ fontSize: 11, color: TX3 }}>Período</span>
            <Input type="date" value={dataInicial} onChange={e => setDataInicial(e.target.value)} disabled={running} />
            <span style={{ fontSize: 11, color: TX3 }}>→</span>
            <Input type="date" value={dataFinal}   onChange={e => setDataFinal(e.target.value)}   disabled={running} />
            
            <div style={{ width: 1, height: 16, background: BDR, margin: '0 8px' }} />
            
            <span style={{ fontSize: 11, color: TX3 }}>Ou guias específicas</span>
            <Input
              value={requisicoesEspecificas}
              onChange={e => setRequisicoesEspecificas(e.target.value)}
              placeholder="Ex: 2605202612345, 2605202612346..."
              disabled={running}
              style={{ width: 340 }}
            />
            
            <div style={{ flex: 1 }} />
            {error && <span style={{ color: '#f87171', fontSize: 12 }}>{error}</span>}
            <Btn onClick={handleExportSemTel}>Baixar pacientes sem telefone</Btn>
            {running
              ? <Btn onClick={() => handleStop({ clearVisual: true })} variant="danger">■ Interromper</Btn>
              : <Btn onClick={handleRun} disabled={!backendOk} variant="primary">▶ Iniciar processamento</Btn>
            }
          </div>

          {/* Info sem telefone */}
          {(semTelInfo.ok || semTelInfo.error) && (
            <div style={{ background: 'rgba(251,191,36,0.06)', border: '0.5px solid rgba(251,191,36,0.15)', borderRadius: 8, padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 12, color: '#fbbf24' }}>Pacientes sem telefone</span>
              <span style={{ fontSize: 11, color: TX2 }}>{semTelInfo.ok ? `${semTelInfo.file}${semTelInfo.updated_at ? ` · ${new Date(semTelInfo.updated_at * 1000).toLocaleString('pt-BR')}` : ''}` : semTelInfo.error}</span>
            </div>
          )}

          {/* Histórico diário */}
          <ExecHistory ger={gerDiario} title="Histórico de Execuções — Análise Diária" />

          {/* Dashboard em tempo real */}
          {(running || logs.length > 0) && (
            <Dashboard
              running={running}
              logs={logs}
              done={!running && logs.length > 0}
              executionSnapshot={execSnap}
              onEnviarIndividual={enviarIndividual}
              enviandoReq={enviandoReq}
            />
          )}

          {/* Log colapsável */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Btn onClick={() => setShowLog(v => !v)} style={{ fontSize: 11 }}>
                {showLog ? '▲ Ocultar log' : '▼ Mostrar log detalhado'}
              </Btn>
            </div>
            {showLog && (
              <LogViewer logs={logs} totalLines={totalLines} running={running} pinned={pinned}
                onScroll={handleScroll}
                onScrollToBottom={() => setPinned(true)}
                onClear={() => { setLogs([]); setTotalLines(0) }}
              />
            )}
          </div>
        </>)}

        {aba === 'documentos'  && <AbaDocumentos />}
        {aba === 'whatsapp'    && <AbaWhatsApp />}
        {aba === 'faturamento' && (
          <AbaFaturamento
            running={running} logs={logs} totalLines={totalLines}
            runContext={runContext} executionSnapshot={execSnap}
            modoTeste={modoTeste}
            onRunStarted={() => { setRunning(true); setRunContext({ mode: 'faturamento', startedAt: new Date().toISOString(), finishedAt: null }); startStream({ reset: true, keepPinned: true }) }}
            onStop={() => handleStop({ clearVisual: true })}
            onOpenLogTab={() => { setAba('analise'); setShowLog(true); setPinned(true) }}
          />
        )}
      </main>

      <style>{`
        @keyframes pulse-d  { 0%,100%{opacity:1} 50%{opacity:.35} }
        @keyframes bar-slide { 0%{transform:translateX(-150%)} 100%{transform:translateX(400%)} }
        input::placeholder { color: #374151; }
        input[type=date]::-webkit-calendar-picker-indicator { filter: invert(1) opacity(.2); cursor: pointer; }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 99px; }
      `}</style>
    </div>
  )
}
