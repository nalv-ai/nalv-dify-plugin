from dify_plugin import DifyPluginEnv, Plugin

plugin = Plugin(DifyPluginEnv(max_request_timeout=120))

if __name__ == "__main__":
    plugin.run()
