def classFactory(iface):
    """Load the GPX Batch Converter plugin."""
    from .plugin import GpxBatchConverterPlugin
    return GpxBatchConverterPlugin(iface)
