import { useEffect, useRef, useState } from 'react'
import type { TrackingFrame } from './generated/TrackingFrame'
import { PitchScene } from './pitch/PitchScene'
import type { CameraView } from './pitch/PitchScene'
import type { PitchEvidence } from './pitch/evidence'

export function Pitch3D({ frame, trail, camera, homeColor, awayColor, frameDurationMs, replaying = false, evidence = null, seekToken = 0 }: {
  frame: TrackingFrame | null
  trail: TrackingFrame[]
  camera: CameraView
  homeColor: string
  awayColor: string
  frameDurationMs: number
  replaying?: boolean
  evidence?: PitchEvidence | null
  seekToken?: number
}) {
  const host = useRef<HTMLDivElement>(null)
  const scene = useRef<PitchScene | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [follow, setFollow] = useState(false)
  const [labels, setLabels] = useState(true)

  useEffect(() => {
    if (!host.current) return
    const onUnavailable = () => setUnavailable(true)
    try {
      scene.current = new PitchScene(host.current, onUnavailable, () => setFollow(false))
    } catch {
      const task = window.setTimeout(onUnavailable, 0)
      return () => window.clearTimeout(task)
    }
    return () => {
      scene.current?.dispose()
      scene.current = null
    }
  }, [])

  useEffect(() => { scene.current?.setCamera(camera) }, [camera])
  useEffect(() => { scene.current?.setFollow(follow) }, [follow])
  useEffect(() => { scene.current?.setLabels(labels) }, [labels])
  useEffect(() => { scene.current?.setEvidence(evidence) }, [evidence])
  useEffect(() => { scene.current?.resetPlayback() }, [seekToken])
  useEffect(() => {
    scene.current?.update(frame, trail, frameDurationMs, homeColor, awayColor, replaying)
  }, [frame, trail, frameDurationMs, homeColor, awayColor, replaying, seekToken])

  return <div className="pitch pitch-3d" role="group" aria-label={`Interactive 3D ${camera} stadium showing simulated football tracking`}>
    <div ref={host} className="webgl-pitch" />
    {unavailable ? <div className="webgl-unavailable" role="status">
      <strong>3D rendering is unavailable</strong>
      <span>Select 2D VIEW above to continue watching the match.</span>
    </div> : <>
      <div className="stadium-tools">
        {evidence && <button type="button" onClick={() => scene.current?.focusEvidence()}>FOCUS EVIDENCE</button>}
        <button type="button" aria-pressed={follow} onClick={() => setFollow(!follow)}>FOLLOW BALL</button>
        <button type="button" aria-pressed={labels} onClick={() => setLabels(!labels)}>PLAYER NUMBERS</button>
        <button type="button" onClick={() => scene.current?.setCamera(camera)}>RESET CAMERA</button>
      </div>
      <div className="stadium-hud"><span><i />{replaying ? 'EVIDENCE REPLAY' : '3D MATCH VIEW'}</span><span>DRAG TO ORBIT / SCROLL TO ZOOM</span></div>
      <span className="stadium-disclosure">SYNTHETIC TRACKING / INTERPOLATED MOVEMENT</span>
    </>}
  </div>
}
