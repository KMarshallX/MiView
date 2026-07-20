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

Right-clicking a straight edge offers **Display the tangent vector** and
**Display the normal vector**. A tangent follows the normalized endpoint order.
A normal starts at the edge midpoint, points 90 degrees counter-clockwise in
physical in-plane space, and is drawn at a fixed 48 logical pixels. Each edge can
own one vector of each kind per projection. Right-click a vector to flip or
delete it. Curving, splitting, or deleting its edge removes derived vectors and
their dependent measurements.

Right-clicking a node offers **Create a vector from this node**. The next click
must use the same projection. Clicking another node completes the vector;
clicking empty projection space first creates a target node using the current
MIP/MinIP ray-resolution rules. Invalid rays create neither node nor vector.

**Calculate Angle** continuously selects an existing source vector and target
vector in the same projection. Each completed directed `0–180°` measurement is
retained as `A1`, `A2`, and so on. Calculations use physical in-plane spacing.
The viewer draws stable preset vector colours, dashed supporting lines, an angle
arc, and a label. Flipping one vector recalculates every dependent measurement.
Cancel exits the tool without deleting completed angles.

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
