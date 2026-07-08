#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { OmniborStack } from '../lib/omnibor-stack';

const app = new cdk.App();

new OmniborStack(app, 'OmniBor', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1',
  },

  // Override via: cdk deploy -c ghcrOwner=kkaple
  // Defaults to 'kkaple' if not specified
});
