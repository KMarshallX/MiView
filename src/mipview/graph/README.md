# Projection Graph Mode

Patch windows provide a sparse graph editor for MIP and MinIP
views. The authoritative graph uses patch-local source-array voxel coordinates;
the axial, coronal, and sagittal overlays are projections of that shared graph.

- Nodes and edges created in one orientation appear in all enabled orientations.
- Completed graph geometry is retained when switching between MIP and MinIP.
- Graphs are rendered and editable only while their orientation is projected.
- Graph mode exits automatically after the last projection is disabled.
- **Save Graph State…** writes persistent graph content to a local
  `.mipgraph.json` file; **Load Graph State…** restores it into a compatible
  patch.

Creating a node from a 2D projection resolves the missing coordinate from the
current image ray: MIP uses the finite maximum and MinIP uses the finite minimum.
The selected projection mask restricts contributing voxels when the clicked ray
crosses the mask. Outside the projected mask region, node creation falls back to
the unmasked image ray using the same MIP/MinIP rule. Equal extrema choose the
depth nearest the current cursor and then the lower index. Fully non-finite rays
fail explicitly. Once resolved, a node does not move when projection mode or mask
changes. This intensity-derived depth is a reviewable aid and is not proof that
the selected voxel represents the intended anatomy.

The command interface retains `graph.add_node` for oriented projection indices.
`graph.add_voxel_node` (CLI: `graph add-voxel-node`) creates an unambiguous node
from patch-local `(x, y, z)` source-array coordinates. Command results and
`graph.status` include patch voxels, full-image voxels when patch bounds exist,
and derived coordinates for all three orientations.

Nodes are stored in dictionaries and edges as normalized node-ID pairs. Optional
quadratic Bezier control points are stored separately from edge identity. Use
**Curve Edge** from the Graph panel or an edge context menu, select an edge, and
drag its projected control handle. Control points are 3D: dragging changes the
two visible coordinates and preserves depth, allowing refinement from another
orientation. **Straighten Edge** removes only the shared control point.
Once the blue control handle is visible, a left-click anywhere outside that
handle exits Curve Edge mode and hides the handle.

Right-clicking a straight or curved edge offers **Create a node here**. The new
node is placed at the nearest projection index on the edge, the original edge is
replaced by two connected edges, and quadratic subdivision preserves curved-edge
geometry.

Right-clicking a straight edge offers **Display the tangent vector** and
**Display the normal vector**. A tangent follows the normalized endpoint order.
A normal starts at the edge midpoint, points 90 degrees counter-clockwise in
physical in-plane space, and is drawn at a fixed 48 logical pixels. Each edge can
own one vector of each kind per projection. Right-click a vector to flip or
delete it. Curving, splitting, or deleting its edge removes derived vectors and
their dependent measurements.

Straight-edge context menus also provide independent **extension line** and
**normal line** toggles. These dashed plane-spanning construction lines do not
create graph vectors, consume vector colour presets, or participate in angle
measurements. Curving, splitting, or deleting the source edge removes its
construction lines and any derived vectors.

Left-clicking a node, edge, or vector selects it and renders that element white.
Left-clicking empty projection space clears the selection while retaining normal
cursor interaction.

Right-clicking a node offers **Create a vector from this node**. The next click
must use the same projection. Clicking another node completes the vector;
clicking empty projection space first creates a target node using the current
MIP/MinIP ray-resolution rules. Invalid rays create neither node nor vector.

**Calculate Angle** selects an existing source vector and target vector in the
same projection. Each vector can belong to only one retained angle pair. The
target, both dashed supporting lines, and the angle label inherit the source
vector's colour; deleting the angle restores the target's original palette
colour. Measurements are directed `0–180°` values calculated with physical
in-plane spacing. Flipping either vector recalculates its measurement.

Double-left-click an angle label to arm it for one move. A white dashed boundary
marks the armed label. The next left drag that starts inside that boundary moves
the label while keeping it inside the rendered projection; releasing locks it
again. Saved positions use normalized projection coordinates so they remain
stable when the patch window is resized.

**Clear All Nodes & Edges** clears the shared graph in every orientation,
including curve controls, pending interactions, and stored angle measurements.

Rendering uses direct `QPainter` primitives and `QPainterPath`, so graph memory
grows with node and edge count rather than patch-volume size.

Graph mode preserves right-drag zoom. A stationary right-click opens the graph
context menu. Edge creation may cross orientations, but vector creation is locked
to the projection where it began. Pressing Escape, exiting Graph mode, changing
MIP/MinIP mode, or disabling the locked projection cancels pending creation.

Changing MIP/MinIP mode also cancels active curve/angle interaction while keeping
completed curves and measurements. An incompatible patch-volume geometry change
clears the shared graph and its measurements.

Graph state files contain a format identifier and schema version, patch geometry,
nodes, edges and curve controls, original vector colours, retained angle pairs and
label positions, construction lines, and Graph-specific display settings. Loading
requires matching patch shape, half-open source bounds, and affine. A different
source path is reported as a warning when geometry remains compatible. Active
tools, selections, pending operations, and Graph activation are not saved.

Version 1 uses this top-level structure:

```json
{
  "format": "mipview-graph-state",
  "version": 1,
  "source": {
    "image_path": "/path/to/source.nii.gz",
    "patch_shape": [64, 64, 10],
    "patch_bounds": {},
    "patch_affine": [],
    "voxel_spacing": []
  },
  "display": {},
  "graph": {"nodes": [], "edges": []},
  "vectors": [],
  "angles": [],
  "construction_lines": {"extension": {}, "normal": {}}
}
```

The loader validates all nested fields and references; the abbreviated objects
above document the container layout rather than valid empty field values.
