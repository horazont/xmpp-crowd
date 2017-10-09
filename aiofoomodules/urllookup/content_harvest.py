class ContentHarvester:
    def __init__(self):
        pass

    def add_image_hook(self, hook):
        pass

    def add_video_hook(self, hook):
        pass

    async def setup(self, main):
        pass

    async def teardown(self):
        pass

    async def __call__(self, ctx, message, document):
        print(ctx, message, document)
