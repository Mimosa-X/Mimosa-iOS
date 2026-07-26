#!/usr/bin/env python3
"""
为新的 bundle_id 重新生成 fake-codesigning provisioning profiles。

该脚本会：
1. 读取 build-system/appstore-configuration.json 中的 bundle_id 和 team_id
2. 解码现有的 .mobileprovision 文件
3. 修改 application-identifier、application-groups、TeamIdentifier 等字段
4. 使用 SelfSigned.p12 重新签名，生成新的 profiles

必须在 macOS 上运行（依赖 security / openssl 命令）。
"""

import json
import os
import sys
import tempfile
import plistlib
import argparse
import subprocess
import base64

from BuildEnvironment import run_executable_with_output


def setup_temp_keychain(p12_path, p12_password=''):
    """创建临时 keychain 并导入 p12 证书。"""
    keychain_name = 'regenerate-profiles-temp.keychain'
    keychain_password = 'temp123'

    # 如果存在则删除
    run_executable_with_output('security', arguments=['delete-keychain', keychain_name], check_result=False)

    # 创建 keychain
    run_executable_with_output('security', arguments=[
        'create-keychain', '-p', keychain_password, keychain_name
    ], check_result=True)

    # 加入搜索列表
    existing = run_executable_with_output('security', arguments=['list-keychains', '-d', 'user'])
    run_executable_with_output('security', arguments=[
        'list-keychains', '-d', 'user', '-s', keychain_name, existing.replace('"', '')
    ], check_result=True)

    # 解锁并设置访问权限
    run_executable_with_output('security', arguments=['set-keychain-settings', keychain_name])
    run_executable_with_output('security', arguments=[
        'unlock-keychain', '-p', keychain_password, keychain_name
    ])

    # 导入证书
    run_executable_with_output('security', arguments=[
        'import', p12_path, '-k', keychain_name, '-P', p12_password,
        '-T', '/usr/bin/codesign', '-T', '/usr/bin/security'
    ], check_result=True)

    # 设置 partition list
    run_executable_with_output('security', arguments=[
        'set-key-partition-list', '-S', 'apple-tool:,apple:', '-k', keychain_password, keychain_name
    ], check_result=True)

    return keychain_name


def cleanup_temp_keychain(keychain_name):
    """删除临时 keychain。"""
    run_executable_with_output('security', arguments=['delete-keychain', keychain_name], check_result=False)


def get_signing_identity_from_p12(p12_path, p12_password=''):
    """从 p12 中提取签名身份（Common Name）。"""
    proc = subprocess.Popen(
        ['openssl', 'pkcs12', '-in', p12_path, '-passin', 'pass:' + p12_password, '-nokeys', '-legacy'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    cert_pem, _ = proc.communicate()

    proc2 = subprocess.Popen(
        ['openssl', 'x509', '-noout', '-subject', '-nameopt', 'oneline,-esc_msb'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    subject, _ = proc2.communicate(cert_pem)
    subject = subject.decode('utf-8').strip()

    if 'CN = ' in subject:
        cn = subject.split('CN = ')[-1].split(',')[0].strip()
        return cn

    return None


def get_certificate_base64_from_p12(p12_path, p12_password=''):
    """从 p12 中提取证书并转为 base64。"""
    proc = subprocess.Popen(
        ['openssl', 'pkcs12', '-in', p12_path, '-passin', 'pass:' + p12_password, '-nokeys', '-legacy'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    cert_pem, _ = proc.communicate()

    proc2 = subprocess.Popen(
        ['openssl', 'x509', '-outform', 'DER'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    cert_der, _ = proc2.communicate(cert_pem)

    return base64.b64encode(cert_der).decode('utf-8')


def decode_provisioning_profile(source):
    """用 openssl 解码 .mobileprovision 文件为 plist dict。"""
    profile_data = run_executable_with_output('openssl', arguments=[
        'smime',
        '-inform',
        'der',
        '-verify',
        '-noverify',
        '-in',
        source
    ], decode=False, stderr_to_stdout=False, check_result=True)
    return plistlib.loads(profile_data)


def sign_provisioning_profile(plist_file, destination, signing_identity, keychain_name):
    """使用 security cms 对 plist 文件进行签名。"""
    run_executable_with_output('security', arguments=[
        'cms', '-S', '-k', keychain_name, '-N', signing_identity, '-i', plist_file, '-o', destination
    ], check_result=True)


def update_profile_for_bundle_id(profile_dict, new_bundle_id, new_team_id, suffix):
    """
    更新 profile dict 以适配新的 bundle_id。

    参数:
        profile_dict: 解码后的 plist dict
        new_bundle_id: 新的 bundle id，例如 ph.mimosa.Mimosa
        new_team_id: 新的 team id
        suffix: application-identifier 的后缀，例如 ''、'.Share'、'.Widget'
    """
    # 更新主 application-identifier
    profile_dict['Entitlements']['application-identifier'] = new_team_id + '.' + new_bundle_id + suffix

    # 更新 application-groups
    if 'com.apple.security.application-groups' in profile_dict['Entitlements']:
        new_groups = []
        for group in profile_dict['Entitlements']['com.apple.security.application-groups']:
            if group.startswith('group.'):
                new_groups.append('group.' + new_bundle_id)
            else:
                new_groups.append(group)
        profile_dict['Entitlements']['com.apple.security.application-groups'] = new_groups

    # 更新 ApplicationIdentifierPrefix
    if 'ApplicationIdentifierPrefix' in profile_dict:
        profile_dict['ApplicationIdentifierPrefix'] = [new_team_id + '.']

    # 更新 TeamIdentifier
    if 'TeamIdentifier' in profile_dict:
        profile_dict['TeamIdentifier'] = [new_team_id]

    # 更新 AppIDName（可选，保持可读性）
    if 'AppIDName' in profile_dict:
        profile_dict['AppIDName'] = new_bundle_id + suffix

    return profile_dict


def regenerate_profiles(source_path, destination_path, certs_path, new_bundle_id, new_team_id):
    """批量重新生成 provisioning profiles。"""
    p12_path = os.path.join(certs_path, 'SelfSigned.p12')

    if not os.path.exists(p12_path):
        print('{} does not exist'.format(p12_path))
        sys.exit(1)

    if not os.path.exists(destination_path):
        os.makedirs(destination_path, exist_ok=True)

    p12_password = ''  # fake-codesigning 使用空密码
    certificate_data = get_certificate_base64_from_p12(p12_path, p12_password)
    signing_identity = get_signing_identity_from_p12(p12_path, p12_password)

    if not signing_identity:
        print('Could not extract signing identity from {}'.format(p12_path))
        sys.exit(1)

    print('Using signing identity: {}'.format(signing_identity))

    keychain_name = setup_temp_keychain(p12_path, p12_password)

    # 文件名 -> application-identifier 后缀映射
    profile_name_mapping = {
        'Telegram': '',
        'Intents': '.SiriIntents',
        'NotificationContent': '.NotificationContent',
        'NotificationService': '.NotificationService',
        'Share': '.Share',
        'WatchApp': '.watchkitapp',
        'WatchExtension': '.watchkitapp.watchkitextension',
        'Widget': '.Widget',
        'BroadcastUpload': '.BroadcastUpload'
    }

    try:
        for file_name in sorted(os.listdir(source_path)):
            if not file_name.endswith('.mobileprovision'):
                continue

            source_file = os.path.join(source_path, file_name)
            profile_base_name = file_name.replace('.mobileprovision', '')
            suffix = profile_name_mapping.get(profile_base_name, '')

            print('Processing {} -> suffix="{}"'.format(file_name, suffix))

            # 解码原 profile
            profile_dict = decode_provisioning_profile(source_file)

            # 更新 bundle id 相关字段
            updated_dict = update_profile_for_bundle_id(profile_dict, new_bundle_id, new_team_id, suffix)

            # 写入临时 plist 文件
            parsed_plist_file = tempfile.mktemp()
            with open(parsed_plist_file, 'wb') as f:
                plistlib.dump(updated_dict, f)

            # 移除旧的 DeveloperCertificates
            while True:
                result = run_executable_with_output('plutil', arguments=['-remove', 'DeveloperCertificates.0', parsed_plist_file], check_result=False)
                if result is None or 'Could not' in str(result) or result == '':
                    check = run_executable_with_output('plutil', arguments=['-extract', 'DeveloperCertificates.0', 'raw', parsed_plist_file], check_result=False)
                    if check is None or 'Could not' in str(check):
                        break

            # 插入新的证书并移除旧签名
            run_executable_with_output('plutil', arguments=['-insert', 'DeveloperCertificates.0', '-data', certificate_data, parsed_plist_file])
            run_executable_with_output('plutil', arguments=['-remove', 'DER-Encoded-Profile', parsed_plist_file])

            # 重新签名
            destination_file = os.path.join(destination_path, file_name)
            sign_provisioning_profile(parsed_plist_file, destination_file, signing_identity, keychain_name)

            os.unlink(parsed_plist_file)

        print('Done. Generated {} profiles.'.format(
            len([f for f in os.listdir(destination_path) if f.endswith('.mobileprovision')])
        ))
    finally:
        cleanup_temp_keychain(keychain_name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Regenerate provisioning profiles for a new bundle id')
    parser.add_argument('--configurationPath', required=True, help='Path to build configuration JSON')
    parser.add_argument('--sourceProfiles', required=True, help='Path to source provisioning profiles directory')
    parser.add_argument('--destinationProfiles', required=True, help='Path to output provisioning profiles directory')
    parser.add_argument('--certsPath', required=True, help='Path to certificates directory containing SelfSigned.p12')

    args = parser.parse_args()

    with open(args.configurationPath) as f:
        config = json.load(f)

    new_bundle_id = config['bundle_id']
    new_team_id = config['team_id']

    print('Regenerating profiles for bundle_id={}, team_id={}'.format(new_bundle_id, new_team_id))
    regenerate_profiles(args.sourceProfiles, args.destinationProfiles, args.certsPath, new_bundle_id, new_team_id)
