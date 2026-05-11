# Annotation I/O

MipView annotation masks are voxel-space integer arrays. Label `0` is reserved
for background, and foreground labels are exported to JSON as compact runs of
linear voxel indices.

## Annotation Panel Export

The annotation panel has an `Export:` dropdown with three choices:

- `NIFTI file` saves only the voxel-space annotation mask as `.nii` or `.nii.gz`.
- `JSON metadata` saves only the RLE-linear metadata as `.json`.
- `Both` saves the NIfTI mask and a JSON metadata sidecar.

Changing the dropdown only selects the export type. It must not open a file
dialog or write files. The save dialog appears only when the user clicks `Save`.

Standalone JSON metadata exports do not write a NIfTI mask, so their
`annotation_mask` field is stored as an empty string.

## Annotation Panel Load

The annotation panel `Load` action accepts `.nii`, `.nii.gz`, and `.json` files.
Loading a NIfTI annotation mask keeps the existing behavior: MipView validates
the mask against the currently loaded base image before enabling annotation
editing.

Loading JSON metadata reconstructs the RLE-linear annotation into a temporary
`.nii.gz` beside the JSON file, validates that reconstructed mask against the
currently loaded base image, then deletes the temporary file. The temporary file
is only used for loading and does not affect later Save or Export behavior.

JSON reconstruction uses MipView's canonical loaded source orientation, not the
raw on-disk source orientation. This keeps JSON-loaded annotations aligned with
the same annotation loaded directly from NIfTI.

Annotation loading shows a modal progress popup. A base image must already be
loaded before either NIfTI masks or JSON metadata can be loaded.

## Segmentation Configuration Integration

The active annotation mask is also listed in `Segmentation -> Open Configuration
Panel` so users can inspect it alongside other segmentation overlays. Creating a
new annotation layer from the annotation panel registers a segmentation entry
named `Annotating Layer`. Loading an annotation NIfTI mask uses the same display
name. Loading annotation JSON metadata reconstructs the mask first and displays
the entry as `recon_Annotating Layer`.

The segmentation-panel entry does not make annotation data a separate editable
segmentation object. The voxel-space annotation mask remains the source of truth,
and edits must still happen through annotation tools such as paint, erase, active
label, brush radius, and undo.

When `Annotating Layer` is the active item in the segmentation configuration
panel, the segmentation opacity slider controls the same annotation opacity as
the annotation panel. Removing the annotation entry through `Segmentation ->
Unload Current Segmentation` clears the current annotation session and exits
annotation mode.

## RLE-linear Metadata

Flattening annotated voxels makes the JSON small and keeps the format independent
of screen layout. The JSON stores the source mask shape and the flattening
convention so the same voxel coordinates can be reconstructed later.

MipView uses `index_order: "x_fastest_xyz"`:

```text
shape = [X, Y, Z]
i = x + X * (y + Y * z)
```

The inverse mapping is:

```text
x = i % X
y = (i // X) % Y
z = i // (X * Y)
```

In NumPy terms this is equivalent to:

```python
flat = mask.ravel(order="F")
mask = flat.reshape(shape, order="F")
```

Because `x` is the fastest-changing axis, adjacent voxels along `x` become
adjacent linear indices. RLE stores contiguous foreground indices as
`[start_index, run_length]` pairs. For example, indices
`[100, 101, 102, 500, 501]` become:

```json
[[100, 3], [500, 2]]
```

## JSON Example

The `shape` field must stay a flat array. Each non-background label stores its
name, encoding, and RLE runs:

```json
{
  "source_image": "/path/to/image.nii.gz",
  "annotation_mask": "/path/to/annotation.nii.gz",
  "index_order": "x_fastest_xyz",
  "shape": [256, 256, 180],
  "labels": {
    "1": {
      "name": "vessel",
      "encoding": "rle_linear",
      "runs": [[3016824, 3], [3016830, 4], [3016850, 2]]
    }
  },
  "notes": ""
}
```

## Decoding

Decoding validates that:

- `shape` contains three positive integers;
- `index_order` is `x_fastest_xyz`;
- label keys parse as integer label values;
- every label uses exactly `encoding: "rle_linear"`;
- every run is a pair of integers with `start >= 0`, `length > 0`, and
  `start + length <= X * Y * Z`.

The decoder fills a zero-initialized `np.uint8` flat buffer, then reshapes it with
`order="F"` into the stored shape. Preserving both `shape` and `index_order` is
essential: without them, a valid run list could reconstruct to the wrong voxel
coordinates.

`recon_annotation_metadata` decodes the JSON, loads the source NIfTI image through
MipView's canonical loader, checks that the decoded shape matches the canonical
source image shape, then saves the mask with the canonical source affine and a
copied header whose dtype is adjusted to `np.uint8`.
