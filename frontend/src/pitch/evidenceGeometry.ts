import * as THREE from 'three'
import { evidenceZone } from './evidence'
import type { PitchEvidence } from './evidence'

export function buildEvidenceGeometry(evidence: PitchEvidence): THREE.Group {
  const layer = new THREE.Group()
  const sources = new Set(evidence.sourceEventIds)
  const zone = evidenceZone(evidence)
  if (zone) {
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(zone.width, 68), new THREE.MeshBasicMaterial({ color: '#ffd37c', transparent: true, opacity: .12, depthWrite: false }))
    mesh.rotation.x = -Math.PI / 2
    mesh.position.set(zone.x + zone.width / 2 - 52.5, .035, 0)
    layer.add(mesh)
  }
  for (const event of evidence.events) {
    if (!event.location) continue
    const group = new THREE.Group()
    group.userData.eventId = event.event_id
    group.visible = false
    const source = sources.has(event.event_id)
    const material = new THREE.MeshBasicMaterial({ color: source ? '#ffd37c' : '#73c8ce', transparent: true, opacity: source ? .95 : .4, depthWrite: false })
    const from = new THREE.Vector3(event.location.x - 52.5, .15, event.location.y - 34)
    const ring = new THREE.Mesh(new THREE.RingGeometry(.75, .95, 32), material)
    ring.rotation.x = -Math.PI / 2; ring.position.copy(from); group.add(ring)
    if (event.end_location) {
      const to = new THREE.Vector3(event.end_location.x - 52.5, .15, event.end_location.y - 34)
      const direction = to.clone().sub(from)
      const distance = direction.length()
      if (distance > .2) {
        direction.normalize()
        const shaft = new THREE.Mesh(new THREE.CylinderGeometry(source ? .085 : .045, source ? .085 : .045, distance, 6), material)
        shaft.position.copy(from).add(to).multiplyScalar(.5)
        shaft.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction)
        const head = new THREE.Mesh(new THREE.ConeGeometry(.35, .9, 8), material)
        head.position.copy(to).addScaledVector(direction, -.3)
        head.quaternion.copy(shaft.quaternion)
        group.add(shaft, head)
      }
    }
    layer.add(group)
  }
  return layer
}
