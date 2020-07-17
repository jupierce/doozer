import pathlib
from doozerlib.cli import cli, pass_runtime
from doozerlib.runtime import Runtime
from doozerlib.model import Model, Missing
import yaml

DEFAULT_RHEL_7_GOLANG = 'rhel_7_golang_openshift'
DEFAULT_RHEL_8_GOLANG = 'rhel_8_golang_openshift'
DEFAULT_RHEL_GOLANG = 'rhel_golang_openshift'


@cli.command("images:reconcile-upstream", short_help="Make pull requests for openshift/release repo")
@pass_runtime
def reconcile_upstream(runtime: Runtime):
    runtime.initialize(clone_distgits=False, clone_source=False)
    runtime.remove_tmp_working_dir = False

    group_name = runtime.group_config.name
    if not group_name.startswith('openshift-'):
        print('This task should only be run against openshift-X.Y groups')
        exit(1)

    major, minor = group_name.split('-')[-1].split('.')

    working_path = pathlib.Path(runtime.working_dir)
    upstream_base_path = working_path.joinpath('upstream_source')
    upstream_base_path.mkdir(exist_ok=True)

    support_path = working_path.joinpath('support')
    support_path.mkdir(parents=True, exist_ok=True)
    release_path = support_path.joinpath('release')

    if not release_path.exists():
        runtime.git_clone('git@github.com:openshift/release', str(release_path))

    for image_meta in runtime.image_metas():
        logger = image_meta.logger
        if not image_meta.has_source():
            # Nothing to do if there is no upstream
            continue

        source_details: 'SourceDetails' = image_meta.get_source_details()
        source_path = upstream_base_path.joinpath(image_meta.distgit_key)
        if not source_path.exists():
            runtime.git_clone(source_details.get_public_git_url(), str(source_path), gitargs=['--branch', source_details.get_public_git_branch()])

        repo_org, repo_name = source_details.get_public_repo_components()
        ci_config_path = release_path.joinpath('ci-operator', 'config', repo_org, repo_name)
        if not ci_config_path.exists():
            logger.warning(f'Cannot find ci-config directory ({str(ci_config_path)}) for this image; that is unusual!')
            continue

        ci_config_file = ci_config_path.joinpath(f'{repo_org}-{repo_name}-{source_details.get_public_git_branch()}.yaml')
        if not ci_config_file.exists():
            logger.warning(f'Cannot find ci-config file ({str(ci_config_file)}) for this image; that is unusual!')
            continue

        def rewrite_istag(istag, name):
            if istag and 'golang' in istag.tag:
                print(f'Rewriting {name} for {str(ci_config_file)}')
                build_root_istag.name = 'builder'
                build_root_istag.namespace = 'openshift'
                build_root_istag.tag = f'golang-openshift-{major}.{minor}'

        with ci_config_file.open(mode='r', encoding='utf-8') as f:
            d = dict(yaml.safe_load(f))
            ci_config = Model(d)

        build_root_istag = ci_config.build_root.image_stream_tag
        rewrite_istag(build_root_istag, 'build_root')

        if not ci_config.base_images:
            ci_config.base_images = {}

        ci_config.base_images[DEFAULT_RHEL_7_GOLANG] = {
            'name': 'builder',
            'namespace': 'openshift',
            'tag': f'rhel-7-golang-openshift-{major}.{minor}'
        }

        ci_config.base_images[DEFAULT_RHEL_8_GOLANG] = {
            'name': 'builder',
            'namespace': 'openshift',
            'tag': f'rhel-8-golang-openshift-{major}.{minor}'
        }

        ci_config.base_images[DEFAULT_RHEL_GOLANG] = {
            'name': 'builder',
            'namespace': 'openshift',
            'tag': f'golang-openshift-{major}.{minor}'
        }

        for idx, image_def in enumerate(ci_config.images.primitive()):
            for input_name, image_as in image_def.get('inputs', {}).items():
                if 'golang' in input_name:
                    del ci_config.images[idx].inputs[input_name]
                    ci_config.images[idx].inputs[DEFAULT_RHEL_GOLANG] = image_as

        #with ci_config_file.open(mode='w+', encoding='utf-8') as f:
            #yaml.safe_dump(ci_config, sort_keys=True, default_flow_style=False)

        print()
        #import pprint
        #pprint.pprint(ci_config.primitive())
        print(yaml.dump(ci_config.primitive(), sort_keys=True))


