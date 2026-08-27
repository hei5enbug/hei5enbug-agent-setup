# Attachments

Every image on a Confluence page is an attachment on that page. The body only points at it.

## Order

Upload first, then reference. A body that points at an attachment which does not exist yet renders
as a broken placeholder, and fixing it costs another read, modify, and save cycle.

## Two identifiers, one of them wrong

An attachment carries two different identifiers.

| Identifier | Shape | Use |
|---|---|---|
| Attachment id | `att` followed by digits | Attachment management, such as deletion |
| Media file id | UUID | The value a media node in the body expects |

Using the attachment id where the file id belongs does not raise an error. Confluence creates a
new empty attachment named after the identifier string, and readers get a preview failure.

Referencing by download URL avoids the choice:

```
/wiki/download/attachments/PAGE_ID/FILENAME
```

Use that form unless something specifically requires a media node.

## Same name means a new version

Uploading a file under a name that already exists creates a new version of that attachment rather
than a second attachment. The download URL does not change.

This is what makes re-rendering a diagram cheap: rebuild the image, upload it under the same name,
and update only the `height` in the body if the ratio changed.

## Upload paths can be restricted

An upload tool may refuse a path outside the directory it was started in, and the message usually
mentions path traversal rather than the real cause.

When that happens, move the files into a directory the tool accepts, then upload again. A staging
directory inside the repository that version control ignores works well, because the files stay
reachable without becoming part of the repository. Confirm the directory is ignored with
`git check-ignore` before writing anything into it.

If no such directory exists, ask the user where to stage the files rather than guessing.

## Deletion needs approval

Deletion is permanent and removes every version of the attachment.

Before deleting anything:

1. List the attachments you propose to delete and say why each one is not needed.
2. Confirm no body still references them.
3. Wait for an explicit answer.

Do not delete attachments as cleanup after a mistake unless the user agrees. An unused attachment
is harmless. A deleted one that something still referenced is not.

## When upload is unavailable

If the host has no upload path at all:

1. Put the files in one directory.
2. Write the body with the download URLs it will have after upload.
3. Tell the user which files to attach to which page, and that the body is already written for
   those names.

Do not silently drop the images or inline them some other way.
