# Projection Graph Mode

Patch windows provide a sparse, session-only graph editor for MIP and MinIP
views. Graph coordinates are 2D oriented projection-array indices, not screen
pixels and not 3D voxel coordinates.

- Axial, coronal, and sagittal projections each own an independent graph layer.
- Each orientation layer is shared when switching between MIP and MinIP.
- Graphs are rendered and editable only while their orientation is projected.
- Graph mode exits automatically after the last projection is disabled.
- Closing the patch window permanently discards its graph layers.

Nodes are stored in dictionaries and edges as normalized node-ID pairs. Rendering
uses direct `QPainter` primitives, so graph memory grows with node and edge count
rather than patch-volume size.

Graph mode preserves right-drag zoom. A stationary right-click opens the graph
context menu; edge completion uses a left-click on a node in the same orientation.
Pressing Escape, exiting Graph mode, changing MIP/MinIP mode, or disabling the
pending edge's projection cancels edge creation.
