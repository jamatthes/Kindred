import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { RegionPolygon } from './RegionPolygon'

describe('RegionPolygon', () => {
  it('renders a closed path for a polygon shape', () => {
    render(
      <RegionPolygon
        id="r1"
        shape="polygon"
        width={400}
        height={300}
        points={[
          { x: 10, y: 10 },
          { x: 100, y: 10 },
          { x: 100, y: 100 },
        ]}
      />,
    )
    const path = screen.getByTestId('region-polygon')
    expect(path.tagName.toLowerCase()).toBe('path')
    expect(path).toHaveAttribute('d', expect.stringMatching(/^M 10 10 L 100 10 L 100 100 Z$/))
  })

  it('renders an svg circle for a circle shape', () => {
    render(
      <RegionPolygon
        id="r2"
        shape="circle"
        width={400}
        height={300}
        center={{ x: 200, y: 150 }}
        radiusPx={40}
      />,
    )
    const circle = screen.getByTestId('region-polygon')
    expect(circle.tagName.toLowerCase()).toBe('circle')
    expect(circle).toHaveAttribute('cx', '200')
    expect(circle).toHaveAttribute('r', '40')
  })

  it('circle and polygon shapes carry the same tint/dash class vocabulary', () => {
    const { rerender } = render(
      <RegionPolygon id="r3" shape="polygon" width={10} height={10} points={[]} prefScore={9} />,
    )
    expect(screen.getByTestId('region-polygon')).toHaveClass('k-region--pref-9')
    rerender(
      <RegionPolygon id="r3" shape="circle" width={10} height={10} center={{ x: 0, y: 0 }} radiusPx={5} prefScore={9} />,
    )
    expect(screen.getByTestId('region-polygon')).toHaveClass('k-region--pref-9')
  })

  it('falls back to the neutral tint when no preference score exists', () => {
    render(<RegionPolygon id="r4" shape="polygon" width={10} height={10} points={[]} />)
    expect(screen.getByTestId('region-polygon')).toHaveClass('k-region--neutral')
  })

  it('marks the OSM boundary source so attribution can be shown', () => {
    render(
      <RegionPolygon id="r5" shape="polygon" width={10} height={10} points={[]} boundarySource="osm" />,
    )
    expect(screen.getByTestId('region-polygon')).toHaveAttribute('data-boundary-source', 'osm')
  })

  it('defaults boundary source to "drawn" when not a named-locality region', () => {
    render(<RegionPolygon id="r6" shape="polygon" width={10} height={10} points={[]} />)
    expect(screen.getByTestId('region-polygon')).toHaveAttribute('data-boundary-source', 'drawn')
  })

  it('calls onClick with the region id', () => {
    const onClick = vi.fn()
    render(<RegionPolygon id="r7" shape="polygon" width={10} height={10} points={[]} onClick={onClick} />)
    fireEvent.click(screen.getByTestId('region-polygon'))
    expect(onClick).toHaveBeenCalledWith('r7')
  })
})
