from pathlib import Path
from PIL import Image, ImageEnhance, ImageOps
from app.core.processing import check_cancel, unique_path

class ImageEngine:
    def can_handle(self, category): return category == "Image"

    def convert_job(self, job, cancel=None, progress=None):
        check_cancel(cancel)
        return self.convert(job.source, job.target_format, job.output_dir, job.quality, job)

    @staticmethod
    def apply_edits(image, job):
        image = ImageOps.exif_transpose(image)
        if job.width or job.height:
            width = job.width or int(image.width * job.height / image.height)
            height = job.height or int(image.height * job.width / image.width)
            if job.keep_aspect:
                image.thumbnail((width, height), Image.Resampling.LANCZOS)
            else:
                image = image.resize((width, height), Image.Resampling.LANCZOS)
        if job.rotation:
            image = image.rotate(-job.rotation, expand=True)
        if job.flip == "Horizontal":
            image = ImageOps.mirror(image)
        elif job.flip == "Vertical":
            image = ImageOps.flip(image)
        if job.brightness != 1:
            image = ImageEnhance.Brightness(image).enhance(job.brightness)
        if job.contrast != 1:
            image = ImageEnhance.Contrast(image).enhance(job.contrast)
        if job.saturation != 1 and image.mode in ("RGB", "RGBA"):
            image = ImageEnhance.Color(image).enhance(job.saturation)
        if job.border:
            image = ImageOps.expand(image, border=job.border, fill=job.background_color or "white")
        return image

    def preview(self, source, job):
        with Image.open(source) as original:
            image = self.apply_edits(original, job)
            if job.background_color and "A" in image.getbands():
                background = Image.new("RGB", image.size, job.background_color)
                background.paste(image, mask=image.getchannel("A")); image = background
            return image.copy()

    def convert(self, source, target_format, output_dir, quality="Balanced", job=None):
        src = Path(source)
        fmt = target_format.upper()
        if src.suffix.lower() == ".svg" or fmt == "SVG":
            raise RuntimeError("SVG conversion requires an SVG raster/vector plugin; this build supports SVG detection but does not rasterize it silently.")
        ext = {"JPEG": "jpg", "TIFF": "tiff"}.get(fmt, fmt.lower())
        output = unique_path(Path(output_dir) / f"{src.stem}_converted.{ext}")
        with Image.open(src) as original:
            metadata = {
                key: original.info[key]
                for key in ("icc_profile", "exif")
                if key in original.info
            }
            image = self.apply_edits(original, job) if job else ImageOps.exif_transpose(original)
            if job:
                if job.background_color and "A" in image.getbands():
                    background = Image.new("RGB", image.size, job.background_color)
                    background.paste(image, mask=image.getchannel("A")); image = background
            if fmt in ("JPEG", "BMP", "PDF") and image.mode not in ("RGB", "L"):
                background = Image.new("RGB", image.size, "white")
                if "A" in image.getbands():
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            save_fmt = "JPEG" if fmt == "JPEG" else fmt
            quality_value = {"Balanced": 88, "High": 94, "Maximum": 100}.get(quality, 92)
            kwargs = {"quality": quality_value} if fmt in ("JPEG", "WEBP") else {}
            if fmt == "JPEG" and "icc_profile" in metadata:
                kwargs["icc_profile"] = metadata["icc_profile"]
            if fmt in ("PNG", "WEBP", "TIFF") and "exif" in metadata:
                kwargs["exif"] = metadata["exif"]
            if job and job.dpi:
                kwargs["dpi"] = (job.dpi, job.dpi)
            image.save(output, format=save_fmt, **kwargs)
        return str(output)
