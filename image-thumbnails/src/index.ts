import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";
import os from "node:os";
import { exec } from "node:child_process";
import { promisify } from "node:util";
import unzipper from "unzipper";

dotenv.config();

const app = express();
app.use(cors());
app.use(express.json());

const execAsync = promisify(exec);

// Security Check Middleware
app.use((req, res, next) => {
  const secret = process.env.PROCESSOR_SECRET;
  if (!secret) {
    console.warn("No PROCESSOR_SECRET set on server. Rejecting requests.");
    res.status(500).json({ error: "Server misconfigured" });
    return;
  }

  const authHeader = req.headers["authorization"];
  if (authHeader !== `Bearer ${secret}`) {
    res.status(401).json({ error: "Unauthorized" });
    return;
  }
  next();
});

// Helper to download file
async function downloadFile(url: string, destPath: string) {
  const res = await fetch(url);
  if (!res.ok || !res.body) throw new Error(`Failed to download: ${res.statusText}`);
  
  const fileStream = fsSync.createWriteStream(destPath);
  
  // @ts-ignore
  for await (const chunk of res.body) {
    fileStream.write(Buffer.from(chunk));
  }
  fileStream.end();

  return new Promise((resolve, reject) => {
    fileStream.on("finish", resolve);
    fileStream.on("error", reject);
  });
}

// Helper to upload file via presigned PUT
async function uploadFile(url: string, filePath: string, contentType: string) {
  const fileBuffer = await fs.readFile(filePath);
  const res = await fetch(url, {
    method: "PUT",
    headers: {
      "Content-Type": contentType,
      "Content-Length": fileBuffer.length.toString(),
    },
    body: fileBuffer,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Upload failed: ${res.status} - ${text}`);
  }
}

app.post("/process", async (req, res) => {
  const { sourceUrl, destinationUrl, fileType } = req.body;

  if (!sourceUrl || !destinationUrl || !fileType) {
    res.status(400).json({ error: "Missing required fields" });
    return;
  }

  const id = Math.random().toString(36).substring(7);
  const tmpDir = os.tmpdir();
  const sourcePath = path.join(tmpDir, `source_${id}.${fileType}`);
  const destPath = path.join(tmpDir, `dest_${id}.webp`);

  try {
    console.log(`[${id}] Downloading ${fileType}...`);
    await downloadFile(sourceUrl, sourcePath);

    console.log(`[${id}] Processing...`);
    if (fileType === "psd") {
      // Use ImageMagick to extract the flattened composite layer [0]
      // and resize it to max 800x800, converting to webp
      await execAsync(`convert "${sourcePath}[0]" -resize 800x800 -quality 80 "${destPath}"`);
    } else if (fileType === "af") {
      // Affinity files: Extract embedded thumbnail using unzipper
      await new Promise<void>((resolve, reject) => {
        let found = false;
        fsSync.createReadStream(sourcePath)
          .pipe(unzipper.Parse())
          .on("entry", async (entry) => {
            if (
              entry.path === "QuickLook/Thumbnail.jpg" ||
              entry.path === "Preview.png" ||
              entry.path.toLowerCase().endsWith("thumbnail.jpg")
            ) {
              found = true;
              try {
                // Write the embedded thumbnail directly to the destination path
                const extractedBuffer = await entry.buffer();
                await fs.writeFile(destPath, extractedBuffer);
                // We'll leave it as jpg/png, we could convert it to webp using ImageMagick but 
                // the raw thumbnail is small enough usually. Let's just convert it to webp!
                await execAsync(`convert "${destPath}" -resize 800x800 -quality 80 "${destPath}"`);
                resolve();
              } catch (err) {
                reject(err);
              }
            } else {
              entry.autodrain();
            }
          })
          .on("close", () => {
            if (!found) reject(new Error("No embedded thumbnail found in Affinity file."));
          })
          .on("error", reject);
      });
    } else {
      throw new Error(`Unsupported fileType: ${fileType}`);
    }

    console.log(`[${id}] Uploading...`);
    await uploadFile(destinationUrl, destPath, "image/webp");

    console.log(`[${id}] Success!`);
    res.json({ success: true });
  } catch (err: any) {
    console.error(`[${id}] Error:`, err);
    res.status(500).json({ error: err.message || "Processing failed" });
  } finally {
    // Cleanup tmp files
    await fs.unlink(sourcePath).catch(() => {});
    await fs.unlink(destPath).catch(() => {});
  }
});

const port = process.env.PORT || 8080;
app.listen(port, () => {
  console.log(`ImageMagick Processing Server running on port ${port}`);
});
