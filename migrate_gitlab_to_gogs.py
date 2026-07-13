#!/usr/bin/env python3

import requests
import json
import subprocess
import os

import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--source_namespace',
                    help='The namespace in gitlab as it appears in URLs. For example, given the repository address http://mygitlab.com/harry/my-awesome-repo.git, it shows that this repository lies within my personal namespace "harry". Hence I would pass harry as parameter.',
                    required=True)
parser.add_argument('--add_to_private',default=None, action='store_true',help='If you want to add the repositories under your own name, ie. not in any organisation, use this flag.')
parser.add_argument('--add_to_organization',default=None, metavar='organization_name', help='If you want to add all the repositories to an exisiting organisation, please pass the name to this parameter. Organizations correspond to groups in Gitlab. The name can be taken from the URL, for example, if your organization is http://mygogs-repo.com/org/my-awesome-organisation/dashboard then pass my-awesome-organisation here')
parser.add_argument('--source_repo',
                    help='URL to your gitlab repo in the format http://mygitlab.com/',
                    required=True)
parser.add_argument('--target_repo',
                    help='URL to your gogs / gitea repo in the format http://mygogs.com/',
                    required=True)
parser.add_argument('--no_confirm',
                    help='Skip user confirmation of each single step',
                    action='store_true')
parser.add_argument('--skip_existing',
                    help='Skip repositories that already exist on remote without asking the user',
                    action='store_true')
parser.add_argument('--use_ssh',
                    help='Use ssh to pull/push files to repos',
                    action='store_true')
parser.add_argument('--use_push_ssh',
                    help='Use ssh to only to push files to repos',
                    action='store_true')

args = parser.parse_args()

assert args.add_to_private or args.add_to_organization is not None, 'Please set either add_to_private or provide a target oranization name!'

print('In the following, we will check out all repositories from ')
print('the namespace %s to the current directory and push it to '%args.source_namespace)
if args.add_to_private:
    print('your personal account', end='')
else:
    print('to the organisation %s'%args.add_to_organization, end='')
print(' as private repositories.')

if not args.no_confirm:
    input('Hit any key to continue!')

gogs_url = args.target_repo + "/api/v1"
gitlab_url = args.source_repo + '/api/v4'

if 'gogs_token' in os.environ:
    gogs_token=os.environ['gogs_token']
else:
    gogs_token = input(("\n\nPlease provide the gogs access token which we use to access \n"
                        "your account. This is NOT your password! Go to \n"
                        "/user/settings/applications\n"
                        "and click on 'Create new token', and copy and paste the \n"
                        "resulting token which is shown afterwards. It should look \n"
                        "like 3240823dfsaefwio328923490832a.\n\ngogs_token=").format(args.target_repo))
assert len(gogs_token)>0, 'The gogs token cannot be empty!'

if 'gitlab_token' in os.environ:
    gitlab_token=os.environ['gitlab_token']
else:
    gitlab_token = input(("\n\nToken to access your GITLAB account. This is NOT your password! Go to \n"
                        "{}/-/user_settings/personal_access_tokens \n"
                        "and create a token with the \"read_repository\" and \"read_api\" scope \n"
                        "look like glpat-FyfaVh2WwiRiZKxNOKnhGW86MQp1OjUH.01.0w0b3glkk\n"
                        "\ngitlab_token=").format(args.source_repo))
assert len(gitlab_token)>0, 'The gitlab token cannot be empty!'

#tmp_dir = '/home/simon/tmp/gitlab_gogs_migration'
#print('Using temporary directory %s'%tmp_dir)
## Create temporary directory
#try:
    #os.makedirs(tmp_dir)
    #print('Created temporary directory %s'%tmp_dir)
#except FileExistsError as e:
    #pass
#except Exception as e:
    #raise e

#os.chdir(tmp_dir)

print('Getting existing projects from namespace %s...'%args.source_namespace)
s = requests.Session()
project_list = []
headers = {
    "PRIVATE-TOKEN": gitlab_token
}
res = s.get(gitlab_url + '/projects', headers=headers)
assert res.status_code == 200, 'Error when retrieving the projects. The returned html is %s'%res.text
project_list += json.loads(res.text)
print(res.text)
if len(json.loads(res.text)) <= 0:
    raise RuntimeError("Failed to parse reponse from gitlab")


filtered_projects = list(filter(lambda x: x['path_with_namespace'].split('/')[0]==args.source_namespace, project_list))

print('\n\nFinished preparations. We are about to migrate the following projects:')

print('\n'.join([p['path_with_namespace'] for p in filtered_projects]))

if not args.no_confirm:
    if 'yes' != input('Do you want to continue? (please answer yes or no) '):
        print('\nYou decided to cancel...')


for i in range(len(filtered_projects)):
    src_name = filtered_projects[i]['name']
    if args.use_ssh:
        src_url = filtered_projects[i]['ssh_url_to_repo']
    else:
        src_url = filtered_projects[i]['http_url_to_repo']
    src_description = filtered_projects[i]['description']
    is_private = filtered_projects[i]['pages_access_level'] != "enabled"
    dst_name = src_name.replace(' ','-')

    print('\n\nMigrating project %s to project %s now.'%(src_url,dst_name))

    if not args.no_confirm:
        if 'yes' != input('Do you want to continue? (please answer yes or no) '):
            print('\nYou decided to cancel...')
            continue

    # Create repo
    if args.add_to_private:
        print('Posting to:' + gogs_url + '/user/repos')
        create_repo = s.post(gogs_url+'/user/repos', data=dict(token=gogs_token, name=dst_name, private=is_private))

    elif args.add_to_organization:
        print('Posting to:' + gogs_url + '/org/%s/repos')
        create_repo = s.post(gogs_url+'/org/%s/repos'%args.add_to_organization,
                            data=dict(token=gogs_token, name=dst_name, private=is_private, description=src_description))
    if create_repo.status_code != 201:
        print('Could not create repo %s because of %s'%(src_name,json.loads(create_repo.text)['message']))
        if args.skip_existing:
            print('\nSkipped')
        else:
            if 'yes' != input('Do you want to skip this repo and continue with the next? (please answer yes or no) '):
                print('\nYou decided to cancel...')
                exit(1)
        continue

    dst_info = json.loads(create_repo.text)

    if args.use_ssh or args.use_push_ssh:
        dst_url = dst_info['ssh_url']
    else:
        dst_url = dst_info['html_url']

    repo_src_authed = src_url
    if not args.use_ssh:
        #provide the token to skip login
        repo_src_authed = src_url.replace("https://", "https://oauth2:" + gitlab_token + "@")

    # Git pull and push
    subprocess.check_call(['git','clone','--bare', repo_src_authed])
    os.chdir(src_url.split('/')[-1])
    branches=subprocess.check_output(['git','branch','-a'])
    if len(branches) == 0:
        print('\n\nThis repository is empty - skipping push')
    else:
        print(dst_url)
        subprocess.run(['git','push','--mirror',dst_url])
    os.chdir('..')
    subprocess.check_call(['rm','-rf',src_url.split('/')[-1]])

    print('\n\nFinished migration. New project URL is %s'%dst_info['html_url'])
    print('Please open the URL and check if everything is fine.')
    if not args.no_confirm:
        input('Hit any key to continue!')

print('\n\nEverything finished!\n')
