# Projection Graph Mode

Patch windows provide a sparse, session-only graph editor for MIP and MinIP
views. Graph coordinates are 2D oriented projection-array indices, not screen
pixels and not 3D voxel coordinates.

- Axial, coronal, and sagittal projections each own an independent graph layer.
- Each orientation layer is shared when switching between MIP and MinIP.
- Graphs are rendered and editable only while their orientation is projected.
- Graph mode exits automatically after the last projection is disabled.
- Closing the patch window permanently discards its graph layers.

Nodes are stored in dictionaries and edges as normalized node-ID pairs. Optional
quadratic Bezier control points are stored separately from edge identity. Use
**Curve Edge** from the Graph panel or an edge context menu, select an edge, and
drag its control handle. **Straighten Edge** removes only the control point.
Once the blue control handle is visible, a left-click anywhere outside that
handle exits Curve Edge mode and hides the handle.

Right-clicking a straight or curved edge offers **Create a node here**. The new
node is placed at the nearest projection index on the edge, the original edge is
replaced by two connected edges, and quadratic subdivision preserves curved-edge
geometry.

**Calculate Angle** selects four existing nodes in source/target order for two
directed vectors. Both vectors must use one orientation. The displayed unsigned
angle uses the physical in-plane voxel spacing and is therefore not distorted by
anisotropic voxels. Yellow arrows and the result remain until **Clear Angle**;
**Cancel** discards only an incomplete replacement measurement.

Rendering uses direct `QPainter` primitives and `QPainterPath`, so graph memory
grows with node and edge count rather than patch-volume size.

Graph mode preserves right-drag zoom. A stationary right-click opens the graph
context menu; edge completion uses a left-click on a node in the same orientation.
Pressing Escape, exiting Graph mode, changing MIP/MinIP mode, or disabling the
pending edge's projection cancels edge creation.

Changing MIP/MinIP mode also cancels active curve/angle interaction while keeping
completed curves and measurements. A projection-shape change clears the affected
graph layers and any measurements that reference them.
