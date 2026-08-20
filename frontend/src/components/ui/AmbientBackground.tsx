import { useEffect, useRef } from 'react'

/**
 * The dashboard's signature background: two soft, warm gradient washes that
 * drift a few px opposite the pointer, rendered on one <canvas> with a
 * single requestAnimationFrame loop. Deliberately not WebGL -- two radial
 * gradients redrawn per frame is not a workload that benefits from a shader
 * pipeline, and 2D canvas has no GPU-driver surface to fail on. Kept
 * extremely subtle on purpose -- this theme is calm and flat, not "dark
 * tech," so the motion is a whisper, not a signature.
 *
 * Respects prefers-reduced-motion (renders one static frame and stops) and
 * pauses entirely when the tab is hidden, so it never spends a laptop's
 * battery animating something nobody is looking at.
 */
export function AmbientBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    let width = 0
    let height = 0
    let mouseX = 0.5
    let mouseY = 0.5

    function resize() {
      if (!canvas) return
      width = canvas.clientWidth
      height = canvas.clientHeight
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx?.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    function handlePointerMove(e: PointerEvent) {
      mouseX = e.clientX / window.innerWidth
      mouseY = e.clientY / window.innerHeight
    }

    function draw() {
      if (!ctx) return
      ctx.clearRect(0, 0, width, height)

      // Parallax drifts opposite the pointer, subtly -- depth, not a
      // cursor-follower. Capped to a few px so it never fights readability.
      const parallaxX = (mouseX - 0.5) * 24
      const parallaxY = (mouseY - 0.5) * 24

      const gradient = ctx.createRadialGradient(
        width * 0.15 + parallaxX,
        height * 0.1 + parallaxY,
        0,
        width * 0.15,
        height * 0.1,
        width * 0.75,
      )
      gradient.addColorStop(0, 'rgba(239, 185, 58, 0.10)')
      gradient.addColorStop(1, 'rgba(239, 185, 58, 0)')
      ctx.fillStyle = gradient
      ctx.fillRect(0, 0, width, height)

      const gradient2 = ctx.createRadialGradient(
        width * 0.88 - parallaxX,
        height * 0.85 - parallaxY,
        0,
        width * 0.88,
        height * 0.85,
        width * 0.65,
      )
      gradient2.addColorStop(0, 'rgba(24, 20, 15, 0.045)')
      gradient2.addColorStop(1, 'rgba(24, 20, 15, 0)')
      ctx.fillStyle = gradient2
      ctx.fillRect(0, 0, width, height)
    }

    let frame = 0
    let running = true
    function loop() {
      if (!running) return
      draw()
      if (!reduceMotion) frame = requestAnimationFrame(loop)
    }

    function handleVisibility() {
      if (document.hidden) {
        running = false
        cancelAnimationFrame(frame)
      } else {
        running = true
        loop()
      }
    }

    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(canvas)
    resize()
    window.addEventListener('pointermove', handlePointerMove, { passive: true })
    document.addEventListener('visibilitychange', handleVisibility)
    loop()

    return () => {
      running = false
      cancelAnimationFrame(frame)
      resizeObserver.disconnect()
      window.removeEventListener('pointermove', handlePointerMove)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [])

  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden bg-bg">
      <canvas ref={canvasRef} className="h-full w-full" />
    </div>
  )
}
