import { useRef, useState } from 'react'
import type { CSSProperties, PointerEvent } from 'react'
import type { TrackingFrame } from './generated/TrackingFrame'

type Camera = 'broadcast' | 'sideline' | 'goal'

function position(x: number, y: number): CSSProperties {
  return { left: `${Math.max(0, Math.min(100, x / 105 * 100))}%`, top: `${Math.max(0, Math.min(100, y / 68 * 100))}%` }
}

export function Pitch3D({ frame, trail, camera, homeColor, awayColor, frameDurationMs }: {
  frame: TrackingFrame | null
  trail: TrackingFrame[]
  camera: Camera
  homeColor: string
  awayColor: string
  frameDurationMs: number
}) {
  const [orbit, setOrbit] = useState(0)
  const drag = useRef<{ x: number; angle: number } | null>(null)
  const trailPoints = trail.slice(-15).map((item) => `${item.ball.x},${item.ball.y}`).join(' ')

  function pointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.pointerType === 'touch') return
    drag.current = { x: event.clientX, angle: orbit }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function pointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return
    setOrbit(Math.max(-38, Math.min(38, drag.current.angle + (event.clientX - drag.current.x) * .22)))
  }

  return <div
    className={`pitch pitch-3d camera-${camera}`}
    role="img"
    aria-label={`Interactive 3D ${camera} stadium showing simulated football tracking`}
    onPointerDown={pointerDown}
    onPointerMove={pointerMove}
    onPointerUp={() => { drag.current = null }}
    onPointerCancel={() => { drag.current = null }}
  >
    <div className="stadium-glow" />
    <div className="stadium-world" style={{ '--orbit': `${orbit}deg` } as CSSProperties}>
      <div className="stadium-plinth" />
      <div className="stadium-tier stadium-tier-north" />
      <div className="stadium-tier stadium-tier-south" />
      <div className="stadium-tier stadium-tier-west" />
      <div className="stadium-tier stadium-tier-east" />
      <div className="stadium-board"><small>MERIDIAN LEAGUE</small><strong>LIVE MATCH</strong></div>
      {(['nw', 'ne', 'sw', 'se'] as const).map((corner) => <div key={corner} className={`stadium-light light-${corner}`}><span /></div>)}
      <div className="stadium-field">
        <div className="stadium-stripes" />
        <div className="field-outline" />
        <div className="field-centre-line" />
        <div className="field-centre-circle" />
        <div className="field-centre-spot" />
        <div className="field-penalty left" /><div className="field-penalty right" />
        <div className="field-six left" /><div className="field-six right" />
        <div className="field-spot left" /><div className="field-spot right" />
        <div className="field-goal left"><span /></div><div className="field-goal right"><span /></div>
        {trailPoints && <svg className="stadium-trail" viewBox="0 0 105 68" preserveAspectRatio="none" aria-hidden="true"><polyline points={trailPoints} /></svg>}
        {frame?.players.map((player) => {
          const home = player.player_id.startsWith('h')
          const moving = player.speed_kmh > 1.2
          const strideDuration = Math.max(.24, Math.min(.7, 1.15 - player.speed_kmh / 45))
          return <div key={player.player_id} className={`stadium-player ${home ? 'home' : 'away'}${moving ? ' is-moving' : ''}`} style={{ ...position(player.x, player.y), '--kit': home ? homeColor : awayColor, '--frame-duration': `${frameDurationMs}ms`, '--stride-duration': `${strideDuration}s` } as CSSProperties}>
            <span className="player-shadow" />
            <span className="player-figure"><i className="player-head" /><i className="player-shirt" /><i className="player-arm arm-left" /><i className="player-arm arm-right" /><i className="player-shorts" /><i className="player-leg leg-left" /><i className="player-leg leg-right" /></span>
            <span className="player-number">{player.player_id.slice(1)}</span>
          </div>
        })}
        {frame && <div className="stadium-ball" style={{ ...position(frame.ball.x, frame.ball.y), '--frame-duration': `${frameDurationMs}ms` } as CSSProperties}><span className="ball-shadow" /><span className={`ball-sphere${frame.ball_speed_kmh > 2 ? ' rolling' : ''}`} /></div>}
      </div>
      <div className="stadium-front"><span>KELLAN ARENA</span><span>MERIDIAN LEAGUE</span></div>
    </div>
    <div className="stadium-hud"><span><i /> LIVE 3D STADIUM</span><span>DRAG TO ORBIT · SYNTHETIC TRACKING</span></div>
  </div>
}
