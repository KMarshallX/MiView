# Projection Graph Mode

Patch windows provide a sparse, session-only graph editor for MIP and MinIP
views. The authoritative graph uses patch-local source-array voxel coordinates;
the axial, coronal, and sagittal overlays are projections of that shared graph.

- Nodes and edges created in one orientation appear in all enabled orientations.
- Completed graph geometry is retained when switching between MIP and MinIP.
- Graphs are rendered and editable only while their orientation is projected.
- Graph mode exits automatically after the last projection is disabled.
- Closing the patch window permanently discards its graph.

Creating a node from a 2D projection resolves the missing coordinate from the
current image ray: MIP uses the finite maximum and MinIP uses the finite minimum.
The selected projection mask restricts contributing voxels. Equal extrema choose
the depth nearest the current cursor and then the lower index. Empty or non-finite
rays fail explicitly. Once resolved, a node does not move when projection mode or
mask changes. This intensity-derived depth is a reviewable aid and is not proof
that the selected voxel represents the intended anatomy.

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

**Calculate Angle** selects four shared nodes in source/target order for two
directed vectors. All four selections must use one orientation because the result
is the projected view angle, not a 3D angle. It uses physical in-plane voxel
spacing and is therefore not distorted by anisotropic voxels. Yellow arrows and
the result remain until **Clear Angle**; **Cancel** discards only an incomplete
replacement measurement.

Rendering uses direct `QPainter` primitives and `QPainterPath`, so graph memory
grows with node and edge count rather than patch-volume size.

Graph mode preserves right-drag zoom. A stationary right-click opens the graph
context menu. Edge creation may start in one orientation and finish on a shared
node in another. Pressing Escape, exiting Graph mode, changing MIP/MinIP mode, or
disabling the pending edge's projection cancels edge creation.

Changing MIP/MinIP mode also cancels active curve/angle interaction while keeping
completed curves and measurements. An incompatible patch-volume geometry change
clears the shared graph and its measurements.
