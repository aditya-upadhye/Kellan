import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { BallSample, TrackingFrame } from '../generated/TrackingFrame'
import { animateFootballer, createFootballer } from './footballer'
import type { Footballer } from './footballer'
import { interpolate, isDiscontinuity, sampleBallPath, zero } from './motion'
import type { Position } from './motion'
import { buildStadium, createBall } from './stadium'
import { highlightedPlayers, visibleEvidenceEvents } from './evidence'
import type { PitchEvidence } from './evidence'
import { buildEvidenceGeometry } from './evidenceGeometry'

export type CameraView = 'broadcast' | 'sideline' | 'goal'

interface Actor {
  model: Footballer
  start: Position
  end: Position
  incoming: Position
  outgoing: Position
  speed: number
  evidenceRing: THREE.Mesh
}

// Resources are owned by this scene, never shared across renderer instances.
function release(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>()
  const materials = new Set<THREE.Material>()
  const textures = new Set<THREE.Texture>()
  root.traverse((object) => {
    if (object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.Sprite) {
      if ('geometry' in object) geometries.add(object.geometry)
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        materials.add(material)
        for (const value of Object.values(material)) if (value instanceof THREE.Texture) textures.add(value)
      }
    }
    if (object instanceof THREE.InstancedMesh) object.dispose()
    if (object instanceof THREE.Light && 'shadow' in object) (object as THREE.DirectionalLight).shadow.dispose()
  })
  textures.forEach(texture => texture.dispose())
  materials.forEach(material => material.dispose())
  geometries.forEach(geometry => geometry.dispose())
}

export class PitchScene {
  private scene = new THREE.Scene()
  private renderer: THREE.WebGLRenderer
  private camera = new THREE.PerspectiveCamera(49, 1, .2, 340)
  private controls: OrbitControls
  private resize: ResizeObserver
  private actors = new Map<string, Actor>()
  private ball = createBall()
  private ballStart: Position = zero
  private ballEnd: Position = zero
  private ballPath: BallSample[] = []
  private ballCorrection = new THREE.Vector3()
  private ballHeightStart = .25
  private ballHeightEnd = .25
  private clockStart = 0
  private renderedMs = 0
  private evidence: PitchEvidence | null = null
  private evidenceLayer = new THREE.Group()
  private previous: TrackingFrame | null = null
  private segmentStart = 0
  private segmentDuration = 100
  private lastTime = 0
  private replaying = false
  private labels = true
  private follow = false
  private manualOrbit = false
  private view: CameraView = 'broadcast'
  private trail: THREE.Line
  private trailPositions = new Float32Array(15 * 3)
  private selection: THREE.Mesh
  private onUnavailable: () => void
  private onOrbit: () => void

  constructor(host: HTMLDivElement, onUnavailable: () => void, onOrbit: () => void) {
    this.onUnavailable = onUnavailable
    this.onOrbit = onOrbit
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75))
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.toneMappingExposure = 1.05
    this.renderer.domElement.tabIndex = 0
    this.renderer.domElement.setAttribute('aria-label', '3D football pitch. Drag to orbit, scroll to zoom, arrow keys to pan.')
    this.renderer.domElement.addEventListener('webglcontextlost', this.contextLost)
    host.appendChild(this.renderer.domElement)
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = .09
    this.controls.minDistance = 15
    this.controls.maxDistance = 155
    this.controls.minPolarAngle = .15
    this.controls.maxPolarAngle = Math.PI * .46
    this.controls.maxTargetRadius = 50
    this.controls.listenToKeyEvents(this.renderer.domElement)
    this.controls.addEventListener('start', this.orbitStarted)
    buildStadium(this.scene)
    this.scene.add(this.evidenceLayer)
    this.ball.visible = false
    this.scene.add(this.ball)
    const trailGeometry = new THREE.BufferGeometry()
    trailGeometry.setAttribute('position', new THREE.BufferAttribute(this.trailPositions, 3))
    trailGeometry.setDrawRange(0, 0)
    this.trail = new THREE.Line(trailGeometry, new THREE.LineBasicMaterial({ color: '#f3e6a8', transparent: true, opacity: .38 }))
    this.trail.frustumCulled = false
    this.scene.add(this.trail)
    this.selection = new THREE.Mesh(new THREE.RingGeometry(.65, .77, 32), new THREE.MeshBasicMaterial({ color: '#d5f784', transparent: true, opacity: .8, depthWrite: false }))
    this.selection.rotation.x = -Math.PI / 2; this.selection.visible = false; this.scene.add(this.selection)
    this.resize = new ResizeObserver(() => {
      const width = Math.max(1, host.clientWidth), height = Math.max(1, host.clientHeight)
      this.renderer.setSize(width, height)
      this.camera.aspect = width / height
      // Wider vertical field of view on narrow screens keeps the pitch in frame.
      this.camera.fov = this.camera.aspect < 1.2 ? 61 : 49
      this.camera.updateProjectionMatrix()
    })
    this.resize.observe(host)
    this.setCamera('broadcast')
    this.renderer.setAnimationLoop(this.render)
  }

  private contextLost = (event: Event) => {
    event.preventDefault()
    this.renderer.setAnimationLoop(null)
    this.onUnavailable()
  }

  private orbitStarted = () => { this.manualOrbit = true; this.onOrbit() }

  setCamera(view: CameraView) {
    this.view = view
    this.manualOrbit = false
    // Flush damping from the previous camera before applying an exact preset.
    this.controls.enableDamping = false
    this.controls.update()
    const positions: Record<CameraView, [number, number, number]> = {
      broadcast: [0, 66, 78], sideline: [8, 25, 54], goal: [-77, 32, 8],
    }
    this.camera.position.set(...positions[view])
    this.controls.target.set(0, 0, 0)
    this.controls.update()
    this.controls.enableDamping = true
  }

  setFollow(follow: boolean) { this.follow = follow; this.manualOrbit = false }
  resetPlayback() { this.previous = null }

  setEvidence(evidence: PitchEvidence | null) {
    const changed = evidence?.evidenceId !== this.evidence?.evidenceId
    this.scene.remove(this.evidenceLayer)
    release(this.evidenceLayer)
    this.evidenceLayer = evidence ? buildEvidenceGeometry(evidence) : new THREE.Group()
    this.scene.add(this.evidenceLayer)
    this.evidence = evidence
    if (evidence && changed) this.setCamera(this.view)
  }

  focusEvidence() {
    if (!this.evidence) return
    const event = this.evidence.events.find(item => item.event_id === this.evidence?.focusEventId)
    const target = event?.location
      ? new THREE.Vector3(event.location.x - 52.5, 0, event.location.y - 34)
      : this.ball.position.clone().setY(0)
    if (event?.end_location) target.lerp(new THREE.Vector3(event.end_location.x - 52.5, 0, event.end_location.y - 34), .5)
    this.controls.target.copy(target)
    this.camera.position.copy(target).add(new THREE.Vector3(10, 30, 39))
    this.controls.update()
    this.manualOrbit = true
    this.onOrbit()
  }
  setLabels(labels: boolean) {
    this.labels = labels
    this.actors.forEach(actor => { actor.model.label.visible = labels })
  }

  update(frame: TrackingFrame | null, history: TrackingFrame[], duration: number, home: string, away: string, replaying: boolean) {
    if (!frame) return
    if (this.previous?.match_id === frame.match_id && this.previous.frame_seq === frame.frame_seq && this.replaying === replaying) return
    // Finish sampling the active segment before retargeting. A delayed packet or
    // faster playback must not snap players back to the previous input sample.
    const now = performance.now()
    this.sample(now, 0)
    const reset = isDiscontinuity(this.previous, frame, this.replaying !== replaying)
    const source = this.previous
    const prior = new Map(source?.players.map(player => [player.player_id, player]))
    const active = new Set(frame.players.map(player => player.player_id))
    for (const [id, actor] of this.actors) if (!active.has(id)) {
      this.scene.remove(actor.model.root); release(actor.model.root); this.actors.delete(id)
    }
    for (const point of frame.players) {
      let actor = this.actors.get(point.player_id)
      const previousPoint = prior.get(point.player_id)
      const outgoing = previousPoint && !reset ? { x: point.x - previousPoint.x, y: point.y - previousPoint.y } : zero
      const color = point.player_id.startsWith('h') ? home : away
      if (!actor) {
        const model = createFootballer(point.player_id, color)
        model.root.position.set(point.x - 52.5, 0, point.y - 34)
        model.label.visible = this.labels
        const evidenceRing = new THREE.Mesh(new THREE.RingGeometry(.68, .84, 32), new THREE.MeshBasicMaterial({ color: '#ffd37c', transparent: true, opacity: .95, depthWrite: false }))
        evidenceRing.rotation.x = -Math.PI / 2; evidenceRing.position.y = .06; evidenceRing.visible = false
        model.root.add(evidenceRing)
        actor = { model, start: point, end: point, incoming: zero, outgoing, speed: point.speed_kmh, evidenceRing }
        this.actors.set(point.player_id, actor); this.scene.add(model.root)
      }
      actor.model.kit.color.set(color)
      actor.start = reset ? point : { x: actor.model.root.position.x + 52.5, y: actor.model.root.position.z + 34 }
      actor.end = point
      actor.incoming = reset ? zero : actor.outgoing
      actor.outgoing = outgoing
      actor.speed = point.speed_kmh
      if (reset) { actor.model.root.position.set(point.x - 52.5, 0, point.y - 34); actor.model.pace = 0 }
    }
    this.ballStart = reset ? frame.ball : { x: this.ball.position.x + 52.5, y: this.ball.position.z + 34 }
    this.ballEnd = frame.ball
    this.ballHeightEnd = (frame.ball_trajectory?.at(-1)?.height_m ?? 0) + .25
    this.ballHeightStart = reset ? this.ballHeightEnd : this.ball.position.y
    this.clockStart = reset ? frame.clock.ms : (source?.clock.ms ?? frame.clock.ms)
    if (reset) this.ball.position.set(frame.ball.x - 52.5, this.ballHeightEnd, frame.ball.y - 34)
    this.ballPath = !reset && source && frame.clock.ms - source.clock.ms === 1000 ? (frame.ball_trajectory ?? []) : []
    const firstPoint = this.ballPath[0]
    if (firstPoint) this.ballCorrection.set(
      this.ball.position.x - (firstPoint.x - 52.5),
      this.ball.position.y - (firstPoint.height_m + .25),
      this.ball.position.z - (firstPoint.y - 34),
    )
    this.ball.visible = true
    this.segmentStart = now
    this.segmentDuration = Math.max(16, Math.min(1000, duration))
    this.previous = frame
    this.replaying = replaying
    const trail = history.filter(sample => sample.match_id === frame.match_id && sample.clock.period === frame.clock.period && sample.frame_seq <= frame.frame_seq).slice(-15)
    for (let i = 0; i < trail.length; i++) {
      this.trailPositions.set([trail[i].ball.x - 52.5, .06, trail[i].ball.y - 34], i * 3)
    }
    this.trail.geometry.attributes.position.needsUpdate = true
    this.trail.geometry.setDrawRange(0, trail.length)
  }

  private sample(now: number, delta: number) {
    if (!this.previous) return
    const t = Math.max(0, Math.min(1, (now - this.segmentStart) / this.segmentDuration))
    this.renderedMs = this.clockStart + (this.previous.clock.ms - this.clockStart) * t
    const motion = sampleBallPath(this.ballPath, t)
    const bx = motion ? motion.x - 52.5 + this.ballCorrection.x * (1 - t) : this.ballStart.x + (this.ballEnd.x - this.ballStart.x) * t - 52.5
    const bz = motion ? motion.y - 34 + this.ballCorrection.z * (1 - t) : this.ballStart.y + (this.ballEnd.y - this.ballStart.y) * t - 34
    const height = motion ? motion.height_m + .25 + this.ballCorrection.y * (1 - t) : this.ballHeightStart + (this.ballHeightEnd - this.ballHeightStart) * t
    const ballDx = bx - this.ball.position.x, ballDz = bz - this.ball.position.z
    this.ball.position.set(bx, Math.max(.25, height), bz)
    if (Math.hypot(ballDx, ballDz) < 10) {
      this.ball.rotation.x += ballDz / .24
      this.ball.rotation.z -= ballDx / .24
    }
    let closest: Actor | null = null, nearest = 2.2
    for (const actor of this.actors.values()) {
      const point = interpolate(actor.start, actor.end, actor.incoming, actor.outgoing, t)
      const dx = point.x - 52.5 - actor.model.root.position.x
      const dz = point.y - 34 - actor.model.root.position.z
      actor.model.root.position.set(point.x - 52.5, 0, point.y - 34)
      const contact = motion?.actor_id === actor.model.root.name ? motion : null
      if (delta > 0) animateFootballer(actor.model, delta, Math.hypot(dx, dz), actor.speed, dx, dz, this.ball.position, contact, this.ballEnd)
      const distance = actor.model.root.position.distanceTo(this.ball.position)
      if (distance < nearest) { nearest = distance; closest = actor }
    }
    this.selection.visible = closest !== null
    const selectionMaterial = this.selection.material as THREE.MeshBasicMaterial
    selectionMaterial.color.set(motion?.action === 'shot' ? '#ffbd6b' : '#d5f784')
    if (closest) this.selection.position.set(closest.model.root.position.x, .045, closest.model.root.position.z)
  }

  private render = (now: number) => {
    const delta = this.lastTime ? Math.min(.05, (now - this.lastTime) / 1000) : 0
    this.lastTime = now
    this.sample(now, delta)
    const visible = this.evidence ? new Set(visibleEvidenceEvents(this.evidence, this.renderedMs).map(event => event.event_id)) : new Set<string>()
    for (const group of this.evidenceLayer.children) if (group.userData.eventId) group.visible = visible.has(group.userData.eventId)
    const players = this.evidence ? highlightedPlayers(this.evidence, this.renderedMs) : new Set<string>()
    for (const [id, actor] of this.actors) actor.evidenceRing.visible = players.has(id)
    if (this.follow && !this.manualOrbit && this.previous) {
      const factor = 1 - Math.exp(-delta * 2)
      const targetX = this.ball.position.x * (this.view === 'broadcast' ? .28 : .7)
      const targetZ = this.ball.position.z * .25
      const dx = (targetX - this.controls.target.x) * factor
      const dz = (targetZ - this.controls.target.z) * factor
      this.controls.target.x += dx; this.controls.target.z += dz
      this.camera.position.x += dx; this.camera.position.z += dz
    }
    this.controls.update(delta)
    this.renderer.render(this.scene, this.camera)
  }

  dispose() {
    this.renderer.setAnimationLoop(null)
    this.resize.disconnect()
    this.controls.removeEventListener('start', this.orbitStarted)
    this.controls.dispose()
    this.renderer.domElement.removeEventListener('webglcontextlost', this.contextLost)
    release(this.scene)
    this.renderer.dispose()
    this.renderer.forceContextLoss()
    this.renderer.domElement.remove()
    this.actors.clear()
  }
}
