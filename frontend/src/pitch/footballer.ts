import * as THREE from 'three'
import type { BallSample } from '../generated/TrackingFrame'
import type { Position } from './motion'

export interface Footballer {
  root: THREE.Group
  body: THREE.Group
  head: THREE.Group
  hips: THREE.Group[]
  knees: THREE.Group[]
  shoulders: THREE.Group[]
  elbows: THREE.Group[]
  soles: THREE.Object3D[]
  label: THREE.Sprite
  phase: number
  pace: number
  heading: number
  turnRate: number
  kit: THREE.MeshStandardMaterial
}

function mesh(geometry: THREE.BufferGeometry, material: THREE.Material, parent: THREE.Object3D, x: number, y: number, z: number) {
  const part = new THREE.Mesh(geometry, material)
  part.position.set(x, y, z)
  part.castShadow = true
  parent.add(part)
  return part
}

function joint(parent: THREE.Object3D, x: number, y: number, z: number) {
  const group = new THREE.Group()
  group.position.set(x, y, z)
  parent.add(group)
  return group
}

export function createFootballer(id: string, color: string, shirtNumber?: number): Footballer {
  const root = new THREE.Group()
  root.name = id
  // Modest enlargement keeps team kits and joints legible in the wide camera.
  root.scale.setScalar(1.18)
  const seed = [...id].reduce((value, ch) => value + ch.charCodeAt(0), 0)
  const skin = new THREE.MeshStandardMaterial({ color: [0xb97a50, 0x704630, 0xe3af87, 0x925c3e][seed % 4], roughness: .88 })
  const kit = new THREE.MeshStandardMaterial({ color, roughness: .85 })
  const shorts = new THREE.MeshStandardMaterial({ color: '#132330', roughness: .9 })
  const trim = new THREE.MeshStandardMaterial({ color: '#f0f1e4', roughness: .8 })
  const boot = new THREE.MeshStandardMaterial({ color: seed % 3 === 0 ? '#f4b459' : '#192229', roughness: .65 })
  const hair = new THREE.MeshStandardMaterial({ color: '#241e1c', roughness: 1 })
  const body = joint(root, 0, .94, 0)
  const torso = mesh(new THREE.CylinderGeometry(.245, .19, .52, 10), kit, body, 0, .28, 0)
  torso.scale.z = .65
  mesh(new THREE.TorusGeometry(.105, .025, 6, 12), trim, body, 0, .545, 0).rotation.x = Math.PI / 2
  mesh(new THREE.SphereGeometry(.205, 10, 8), shorts, body, 0, -.015, 0).scale.set(1.1, .65, .8)
  const head = joint(body, 0, .59, 0)
  mesh(new THREE.CylinderGeometry(.068, .075, .1, 8), skin, head, 0, 0, 0)
  mesh(new THREE.SphereGeometry(.135, 12, 10), skin, head, 0, .13, .006).scale.set(.85, 1.12, .95)
  mesh(new THREE.SphereGeometry(.138, 12, 8, 0, Math.PI * 2, 0, Math.PI * .48), hair, head, 0, .175, -.01).scale.z = .93
  mesh(new THREE.SphereGeometry(.029, 6, 6), skin, head, 0, .13, .125)
  mesh(new THREE.BoxGeometry(.28, .045, .025), trim, body, 0, .42, .16)
  const hips: THREE.Group[] = [], knees: THREE.Group[] = []
  const shoulders: THREE.Group[] = [], elbows: THREE.Group[] = []
  const soles: THREE.Object3D[] = []
  for (const side of [-1, 1]) {
    const hip = joint(body, side * .115, -.07, 0)
    mesh(new THREE.CapsuleGeometry(.09, .22, 4, 8), skin, hip, 0, -.18, 0)
    mesh(new THREE.CylinderGeometry(.108, .10, .19, 8), shorts, hip, 0, -.07, 0)
    const knee = joint(hip, 0, -.37, 0)
    mesh(new THREE.CapsuleGeometry(.065, .2, 4, 8), skin, knee, 0, -.15, 0)
    mesh(new THREE.CylinderGeometry(.073, .055, .23, 8), kit, knee, 0, -.22, 0)
    const foot = mesh(new THREE.BoxGeometry(.135, .095, .26), boot, knee, 0, -.37, .055)
    for (const z of [-.11, .11]) soles.push(joint(foot, 0, -.0475, z))
    const shoulder = joint(body, side * .26, .45, 0)
    shoulder.rotation.z = side * .13
    mesh(new THREE.CapsuleGeometry(.075, .18, 4, 8), skin, shoulder, 0, -.13, 0)
    mesh(new THREE.CylinderGeometry(.095, .08, .17, 8), kit, shoulder, 0, -.035, 0)
    const elbow = joint(shoulder, 0, -.26, 0)
    mesh(new THREE.CapsuleGeometry(.055, .18, 4, 8), skin, elbow, 0, -.12, 0)
    hips.push(hip); knees.push(knee); shoulders.push(shoulder); elbows.push(elbow)
  }
  const canvas = document.createElement('canvas')
  canvas.width = 128; canvas.height = 64
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = 'rgba(8,19,27,.83)'
  ctx.beginPath(); ctx.roundRect(14, 8, 100, 48, 14); ctx.fill()
  ctx.fillStyle = '#fff'; ctx.font = 'bold 32px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(shirtNumber === undefined ? '?' : String(shirtNumber), 64, 33)
  const map = new THREE.CanvasTexture(canvas)
  map.colorSpace = THREE.SRGBColorSpace
  const label = new THREE.Sprite(new THREE.SpriteMaterial({ map, depthWrite: false, transparent: true }))
  label.position.y = 2.3; label.scale.set(2.5, 1.25, 1)
  root.add(label)
  const shirtCanvas = document.createElement('canvas')
  shirtCanvas.width = 64; shirtCanvas.height = 64
  const shirtContext = shirtCanvas.getContext('2d')!
  shirtContext.fillStyle = '#fff'; shirtContext.font = 'bold 48px sans-serif'
  shirtContext.textAlign = 'center'; shirtContext.textBaseline = 'middle'
  shirtContext.fillText(shirtNumber === undefined ? '?' : String(shirtNumber), 32, 34)
  const shirtMap = new THREE.CanvasTexture(shirtCanvas)
  shirtMap.colorSpace = THREE.SRGBColorSpace
  const shirt = mesh(new THREE.PlaneGeometry(.27, .28), new THREE.MeshBasicMaterial({ map: shirtMap, transparent: true, depthWrite: false }), body, 0, .3, -.169)
  shirt.rotation.y = Math.PI
  return { root, body, head, hips, knees, shoulders, elbows, soles, label, phase: seed, pace: 0, heading: 0, turnRate: 0, kit }
}

const solePosition = new THREE.Vector3()

export function animateFootballer(player: Footballer, delta: number, distance: number, speed: number, dx: number, dz: number, ball: THREE.Vector3, contact: BallSample | null, ballEnd: Position, recordedFacing?: number) {
  const moving = distance > .0001
  const response = 1 - Math.exp(-delta * 14)
  player.pace += ((moving ? Math.min(1, speed / 20) : 0) - player.pace) * response
  const ballHeading = Math.atan2(ball.x - player.root.position.x, ball.z - player.root.position.z)
  const nearBall = player.root.position.distanceTo(ball) < 3
  const kicking = contact && nearBall && (contact.action === 'pass' || contact.action === 'shot')
  const windup = kicking && contact.preparing ? contact.progress : 0
  const kick = kicking && !contact.preparing ? Math.max(0, 1 - contact.progress * 3) : 0
  const receiving = contact?.action === 'receive' && nearBall ? 1 - contact.progress : 0
  const block = contact?.action === 'block' && nearBall ? 1 - contact.progress : 0
  const save = contact?.action === 'save' && nearBall ? 1 - contact.progress : 0
  const desired = kick > .1
    ? Math.atan2(ballEnd.x - 52.5 - player.root.position.x, ballEnd.y - 34 - player.root.position.z)
    : moving ? Math.atan2(dx, dz) : ballHeading
  const turn = Math.atan2(Math.sin(desired - player.heading), Math.cos(desired - player.heading))
  // Sprinting players need time to change direction. Accelerate the turn and
  // cap angular speed, rather than spinning the body toward every new sample.
  const maxTurnRate = 5.5 - player.pace * 2.5
  const desiredTurnRate = Math.max(-maxTurnRate, Math.min(maxTurnRate, turn * 7))
  player.turnRate += (desiredTurnRate - player.turnRate) * (1 - Math.exp(-delta * 10))
  const turnStep = player.turnRate * delta
  player.heading += Math.sign(turnStep) === Math.sign(turn) ? Math.sign(turn) * Math.min(Math.abs(turn), Math.abs(turnStep)) : 0
  if (recordedFacing !== undefined) player.heading = recordedFacing
  player.root.rotation.y = player.heading
  // Cadence follows distance, capped at fast playback so legs remain readable.
  player.phase += moving ? Math.min(distance * 2.8, delta * 23) : delta * player.pace * 3
  const stride = Math.sin(player.phase) * (.2 + player.pace * .6) * Math.min(1, player.pace * 4)
  const controlling = contact?.action === 'carry' && nearBall && speed < 22
  player.body.position.y = .9
  player.body.rotation.x = player.pace * .12 + kick * .13 + windup * .08 + receiving * .08 + block * .12
  player.body.rotation.y = Math.max(-.18, Math.min(.18, turn * .2)) * player.pace
  player.body.rotation.z = -Math.max(-.12, Math.min(.12, player.turnRate * .035)) * player.pace
  player.head.rotation.y = Math.max(-.65, Math.min(.65, Math.atan2(Math.sin(ballHeading - player.heading), Math.cos(ballHeading - player.heading))))
  for (let i = 0; i < 2; i++) {
    const swing = i === 0 ? stride : -stride
    player.hips[i].rotation.x = i === 1 && (kick > 0 || windup > 0 || receiving > 0 || block > 0) ? windup * .65 - kick * 1.05 - receiving * .25 - block * .55 : swing - (controlling && i === 1 ? .18 * player.pace : 0)
    player.knees[i].rotation.x = i === 1 && (kick > 0 || windup > 0) ? kick * .2 + windup * .85 : Math.max(0, -swing) * 1.2 + receiving * .15
    player.shoulders[i].rotation.x = -swing * .8 - kick * (i === 0 ? .25 : -.15) - save * 1.25
    player.shoulders[i].rotation.z = (i === 0 ? -1 : 1) * (.13 + kick * .25)
    player.elbows[i].rotation.x = -.15 - player.pace * .65
  }
  // Plant the supporting sole at turf height. This also prevents skating above
  // the ground when knee bends shorten the leg during a running stride.
  player.root.updateWorldMatrix(true, true)
  let lowest = Infinity
  for (const sole of player.soles) lowest = Math.min(lowest, sole.getWorldPosition(solePosition).y)
  player.body.position.y -= lowest / player.root.scale.y
}
